"""Java library symbols from class files (ADR-017): the reader, the jar lookup, and resolution through libraries."""
import sqlite3
import struct
from pathlib import Path

import pytest

from src.code import classfiles
from src.code.store import CodeStore
from tests.test_code import SAMPLE, find

JDK = classfiles.jdk_home()
needs_jdk = pytest.mark.skipif(JDK is None, reason="no JDK with jmods found on this machine (SEARCHABLES_JAVA_HOME)")


def test_signature_parsing_tracks_the_first_type_variable():
    assert classfiles._class_type_params("<T:Ljava/lang/Object;>Ljava/lang/Object;") == ["T"]
    assert classfiles._class_type_params("<K:Ljava/lang/Object;V:Ljava/lang/Object;>Ljava/lang/Object;") == ["K", "V"]
    assert classfiles._signature_types("(Ljava/lang/Object;)TT;", ["T"]) == ("$T", "")
    assert classfiles._signature_types("()Ljava/util/Optional<TT;>;", ["T"]) == ("java.util.Optional", "$T")
    assert classfiles._signature_types("()Ljava/util/List<Ljava/lang/String;>;", []) == ("java.util.List", "java.lang.String")
    assert classfiles._signature_types("(Ljava/lang/Object;)TV;", ["K", "V"]) == ("", "")   # Only the first variable is followed
    assert classfiles._param_count("(ILjava/lang/String;[J)V") == 3 and classfiles._param_count("()V") == 0


@needs_jdk
def test_reads_the_public_api_of_core_classes():
    import zipfile
    with zipfile.ZipFile(JDK / "jmods" / "java.base.jmod") as archive:
        optional = classfiles.read_class(archive.read("classes/java/util/Optional.class"))
        stream = classfiles.read_class(archive.read("classes/java/util/stream/Stream.class"))
        system = classfiles.read_class(archive.read("classes/java/lang/System.class"))
    assert optional.qualified == "java.util.Optional" and optional.type_params == ["T"] and optional.kind == "class"
    or_else = next(m for m in optional.members if m.name == "orElse")
    assert (or_else.returns, or_else.carried, or_else.params) == ("$T", "", 1)
    find_first = next(m for m in stream.members if m.name == "findFirst")
    assert (find_first.returns, find_first.carried) == ("java.util.Optional", "$T")
    out = next(m for m in system.members if m.name == "out")
    assert (out.kind, out.returns, out.static) == ("field", "java.io.PrintStream", True)
    assert not any(m.name == "<clinit>" for m in system.members) and all(m.name for m in system.members)


def test_a_broken_class_file_is_skipped(tmp_path):
    assert classfiles.read_class(b"not a class") is None
    assert classfiles.read_class(b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 61, 1)) is None


def test_finds_a_declared_jar_in_the_local_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHABLES_MAVEN_REPO", str(tmp_path / "m2"))
    monkeypatch.setenv("SEARCHABLES_GRADLE_CACHE", str(tmp_path / "gradle"))
    assert classfiles.find_jar("com.acme", "thing", "1.2") is None
    jar = tmp_path / "gradle/com.acme/thing/1.2/abc123/thing-1.2.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"")
    assert classfiles.find_jar("com.acme", "thing", "1.2") == jar
    assert classfiles.find_jar("com.acme", "thing", "${version}") is None


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCHABLES_LIBRARIES", "1")
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return CodeStore(conn)


@needs_jdk
def test_calls_resolve_through_library_classes(store):
    codebase = store.add(str(SAMPLE), "Demo")
    store.index(codebase.id)
    jars = store.conn.execute("SELECT path, classes FROM code_jars").fetchall()
    assert any(j["path"].endswith("java.base.jmod") and j["classes"] > 3000 for j in jars)
    controller = next(f for f in store.files(codebase.id) if f.path.endswith("UserController.java"))
    service = next(f for f in store.files(codebase.id) if f.path.endswith("UserService.java"))
    targets = {(r["name"], r["line"]): r["target"] for r in store.conn.execute(
        "SELECT name, line, target FROM code_refs WHERE file_id IN (?, ?) AND kind = 'call'", (controller.id, service.id))}
    assert targets[("println", 27)] == "java.io.PrintStream#println"          # System.out: a static field of a library class
    assert targets[("stream", 13)] == "java.util.Collection#stream"           # Declared on Collection, called on List
    assert targets[("filter", 13)] == "java.util.stream.Stream#filter" and targets[("findFirst", 13)] == "java.util.stream.Stream#findFirst"
    assert targets[("orElse", 20)] == "java.util.Optional#orElse"
    assert targets[("add", 19)] == "java.util.List#add"                      # List declares add itself
    by_name = store.conn.execute("SELECT name FROM code_refs WHERE codebase_id = ? AND kind = 'call' AND target_id IS NULL AND target IS NULL "
                                 "AND file_id IN (SELECT id FROM code_files WHERE language = 'java')", (codebase.id,)).fetchall()
    assert {r["name"] for r in by_name} <= {"unknownThing", "save", "getId"}  # What no library can tell (getId is on an untyped lambda parameter)


@needs_jdk
def test_completion_lists_library_members_with_example_counts(store):
    from src.code.complete import complete_at
    from src.code.context import context_at
    codebase = store.add(str(SAMPLE), "Demo")
    store.index(codebase.id)
    service = next(f for f in store.files(codebase.id) if f.path.endswith("UserService.java"))
    text = store.text(service.id)
    marker = "    private void audit(String what) {\n"
    position = text.index(marker) + len(marker)
    typed = "        users.stream().fi"
    buffer = text[:position] + typed + "\n" + text[position:]
    line = buffer.count("\n", 0, position) + 1
    items = complete_at(store, context_at(store, service.id, buffer, line, len(typed) + 1))
    by_name = {i.name: i for i in items}
    assert "filter" in by_name and "findFirst" in by_name and by_name["filter"].kind == "api"
    assert by_name["filter"].examples == 1 and "Stream" in by_name["filter"].signature
    assert by_name["findFirst"].detail == "java.util.stream.Stream"


@needs_jdk
def test_a_jar_is_read_once_and_shared(store, tmp_path):
    a = store.add(str(SAMPLE), "A")
    store.index(a.id)
    first = store.conn.execute("SELECT id, read_at FROM code_jars ORDER BY id").fetchall()
    b = store.add(str(Path(__file__).parent / "codebase_examples"), "B")
    store.index(b.id)
    again = store.conn.execute("SELECT id, read_at FROM code_jars ORDER BY id").fetchall()
    assert [tuple(r) for r in first] == [tuple(r) for r in again][:len(first)]
    assert store.conn.execute("SELECT COUNT(*) FROM code_codebase_jars WHERE codebase_id = ?", (b.id,)).fetchone()[0] >= 1
