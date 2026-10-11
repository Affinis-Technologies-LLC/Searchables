"""
The writable editor's server side (ADR-011): what may be written where, atomic and checked saves,
files kept in their own form, and the index settled after each save.
"""
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.code.store import CodeStore, Conflict
from tests.test_code import SAMPLE, find


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return CodeStore(conn)


@pytest.fixture
def code(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "project")
    codebase = store.add(str(tmp_path / "project"), "Demo")
    store.index(codebase.id)
    return store.get(codebase.id)


def file_named(store, code, ending):
    return next(f for f in store.files(code.id) if f.path.endswith(ending))


def disk_listing(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


# ---- Saving ------------------------------------------------------------------------------------

def test_a_save_writes_the_file_and_settles_the_index(store, code):
    before = disk_listing(Path(code.root))
    service = file_named(store, code, "UserService.java")
    text = store.text(service.id).replace("private void audit(String what)", "private void audit(String what, int level)") \
                                  .replace('audit("save")', 'audit("save", 1)')
    saved = store.save_file(service.id, text, service.sha256)
    assert saved.id == service.id and saved.sha256 != service.sha256                      # The same file, with a new hash
    assert (Path(code.root) / service.path).read_text().count("int level") == 1
    audit = find(store, code, "com.acme.service.UserService#audit")
    assert audit.params == 2 and [u.line for u in store.usages(audit)] == [18]
    save = find(store, code, "com.acme.service.UserService#save", params=2)
    assert [u.path.rsplit("/", 1)[-1] for u in store.usages(save)] == ["UserController.java"]  # Elsewhere still linked
    # Nothing else on disk changed; no temporary file was left behind
    after = disk_listing(Path(code.root))
    assert {k for k in before if before[k] != after.get(k)} == {service.path} and set(after) == set(before)
    # The index equals a full rescan's
    partial = store.conn.execute("SELECT name, line, target_id, target FROM code_refs WHERE codebase_id = ? ORDER BY file_id, line, col, name", (code.id,)).fetchall()
    store.index(code.id)
    full = store.conn.execute("SELECT name, line, target_id, target FROM code_refs WHERE codebase_id = ? ORDER BY file_id, line, col, name", (code.id,)).fetchall()
    assert [tuple(r) for r in partial] == [tuple(r) for r in full]


def test_unchanged_symbols_keep_their_ids(store, code):
    service = file_named(store, code, "UserService.java")
    before = {(s.qualified, s.params): s.id for s in store.outline(service.id)}
    store.save_file(service.id, store.text(service.id) + "\n// a comment\n", service.sha256)
    after = {(s.qualified, s.params): s.id for s in store.outline(service.id)}
    assert after == before


def test_a_stale_save_is_refused_and_nothing_written(store, code):
    service = file_named(store, code, "UserService.java")
    path = Path(code.root) / service.path
    path.write_text(path.read_text() + "\n// changed outside the editor\n")     # Another editor, or git pull
    with pytest.raises(Conflict) as refused:
        store.save_file(service.id, "package com.acme.service; class UserService {}", service.sha256)
    assert "changed outside" in refused.value.current_text and refused.value.current_sha256 != service.sha256
    assert "changed outside" in path.read_text() and "class UserService {}" not in path.read_text()
    saved = store.save_file(service.id, refused.value.current_text + "// mine\n", refused.value.current_sha256)
    assert saved.sha256 == hashlib.sha256((refused.value.current_text + "// mine\n").encode()).hexdigest()


def test_files_keep_their_line_endings_and_encodings(store, tmp_path):
    root = tmp_path / "forms"
    root.mkdir()
    source = "package p;\r\npublic class A {\r\n    void run() { }\r\n}\r\n"
    (root / "Crlf.java").write_bytes(source.encode("utf-8"))
    (root / "Bom.java").write_bytes(b"\xef\xbb\xbf" + source.replace("A", "B").replace("\r\n", "\n").encode("utf-8"))
    (root / "Wide.java").write_bytes(source.replace("A", "C").encode("utf-16"))
    codebase = store.add(str(root))
    store.index(codebase.id)
    for name, check in (("Crlf.java", lambda b: b.count(b"\r\n") == 4 and b"\n" not in b.replace(b"\r\n", b"")),
                        ("Bom.java", lambda b: b.startswith(b"\xef\xbb\xbf") and b"\r" not in b),
                        ("Wide.java", lambda b: b[:2] in (b"\xff\xfe", b"\xfe\xff") and b.decode("utf-16").count("run2") == 1)):
        file = file_named(store, codebase, name)
        store.save_file(file.id, store.text(file.id).replace("run()", "run2()"), file.sha256)
        written = (root / name).read_bytes()
        assert check(written), name
        assert "run2" in store.text(file.id) and "\r" not in store.text(file.id)


# ---- Where the server may write ----------------------------------------------------------------

def test_writes_outside_the_folder_or_to_other_kinds_are_refused(store, code, tmp_path):
    outside = tmp_path / "elsewhere.java"
    for bad in ("../elsewhere.java", "/etc/passwd", "backend/../../elsewhere.java", "frontend/node_modules/x.js",
                "backend/.git/config", "backend/notes.txt", "backend/src/App.py"):
        with pytest.raises(ValueError):
            store.create_file(code.id, bad, "x")
    assert not outside.exists()
    link = Path(code.root) / "backend" / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(ValueError):
        store.create_file(code.id, "backend/link/escape.java", "class Escape {}")
    assert not (tmp_path / "escape.java").exists()


def test_create_rename_move_and_delete(store, code):
    created = store.create_file(code.id, "backend/src/main/java/com/acme/model/Role.java",
                                "package com.acme.model;\n\npublic class Role { public String name() { return \"r\"; } }\n")
    assert created.language == "java" and find(store, code, "com.acme.model.Role#name")
    assert (Path(code.root) / created.path).exists()
    with pytest.raises(ValueError):
        store.create_file(code.id, created.path, "again")                                 # Exists already

    moved = store.rename_file(created.id, "backend/src/main/java/com/acme/service/Role.java", created.sha256)
    assert moved.id == created.id and not (Path(code.root) / created.path).exists() and (Path(code.root) / moved.path).exists()
    assert find(store, code, "com.acme.model.Role").path == moved.path                     # Package text unchanged; file moved
    with pytest.raises(Conflict):
        store.rename_file(moved.id, "backend/src/main/java/com/acme/Other.java", "stale")
    with pytest.raises(ValueError):
        store.rename_file(moved.id, "backend/src/main/java/com/acme/service/UserService.java", moved.sha256)   # Onto another

    store.delete_file(moved.id, moved.sha256)
    assert not (Path(code.root) / moved.path).exists() and store.file(moved.id) is None
    assert not [s for s in store.search_symbols(code.id, "Role") if s.name == "Role"]


def test_replace_in_files_is_all_or_nothing(store, code):
    controller = file_named(store, code, "UserController.java")
    service = file_named(store, code, "UserService.java")
    changes = [{"file_id": controller.id, "sha256": controller.sha256, "text": store.text(controller.id).replace("service", "svc")},
               {"file_id": service.id, "sha256": "stale", "text": "broken"}]
    with pytest.raises(Conflict):
        store.replace_in_files(code.id, changes)
    assert "svc" not in (Path(code.root) / controller.path).read_text()                  # Neither was written
    changes[1]["sha256"] = service.sha256
    changes[1]["text"] = store.text(service.id).replace("audit", "record")
    saved = store.replace_in_files(code.id, changes)
    assert {f.path.rsplit("/", 1)[-1] for f in saved} == {"UserController.java", "UserService.java"}
    assert find(store, code, "com.acme.service.UserService#record")


def test_a_template_can_be_saved_too(store, tmp_path):
    shutil.copytree(SAMPLE.parent / "codebase_web", tmp_path / "web")
    codebase = store.add(str(tmp_path / "web"))
    store.index(codebase.id)
    template = file_named(store, codebase, "user-list.component.html")
    saved = store.save_file(template.id, store.text(template.id).replace("choose(user)", "choose(user); remove(user)"), template.sha256)
    assert saved.language == "html"
    remove = next(s for s in store.search_symbols(codebase.id, "remove") if s.qualified == "UserListComponent#remove")
    assert [u.line for u in store.usages(remove) if u.path.endswith(".html")] == [3, 4]


def test_the_linker_state_is_reused_between_saves(store, code):
    service = file_named(store, code, "UserService.java")
    store.save_file(service.id, store.text(service.id) + "\n", service.sha256)
    first = store._linkers[code.id]
    file = store.file(service.id)
    store.save_file(service.id, store.text(service.id) + "\n", file.sha256)
    assert store._linkers[code.id] is first
    store.index(code.id)
    assert code.id not in store._linkers                                                  # A rescan starts afresh
