"""The code index, on a small Java back end with a TypeScript/JavaScript front end (tests/codebase)."""
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.code import manifests
from src.code.models import BY_NAME, RESOLVED, SUPERTYPE
from src.code.parser import parse
from src.code.store import CodeStore, normalize_path, paths_match

SAMPLE = Path(__file__).parent / "codebase"


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return CodeStore(conn)


@pytest.fixture
def code(store, tmp_path):
    """The sample codebase, copied so tests can change it, and indexed."""
    shutil.copytree(SAMPLE, tmp_path / "project")
    codebase = store.add(str(tmp_path / "project"), "Demo")
    store.index(codebase.id)
    return store.get(codebase.id)


def find(store, code, qualified, params=None):
    symbols = [s for s in store.search_symbols(code.id, qualified.split("#")[-1].split(".")[-1])
               if s.qualified == qualified and (params is None or s.params == params)]
    assert symbols, f"no symbol {qualified}"
    return symbols[0]


def where(usages, certainty=None):
    return sorted(f"{u.path.rsplit('/', 1)[-1]}:{u.line}" for u in usages if certainty is None or u.certainty == certainty)


# ---- Scanning ----------------------------------------------------------------------------------

def test_scan_reads_source_and_skips_dependencies_and_bundles(store, code):
    paths = [f.path for f in store.files(code.id)]
    assert len(paths) == code.file_count == 10
    assert "frontend/src/components/UserCard.tsx" in paths
    assert not any("node_modules" in p or p.endswith(".min.js") for p in paths)
    assert {f.language for f in store.files(code.id)} == {"java", "javascript", "typescript"}


def test_rescan_reads_only_what_changed(store, code):
    assert store.index(code.id)["changed"] == 0
    root = Path(code.root)
    (root / "frontend/src/util.js").write_text("function format(v) { return '' + v; }\nfunction extra() {}\nmodule.exports = { format };\n")
    (root / "backend/src/main/java/com/acme/model/User.java").unlink()
    result = store.index(code.id)
    assert (result["changed"], result["removed"]) == (1, 1)
    assert [s.name for s in store.search_symbols(code.id, "extra")] == ["extra"]
    assert store.search_symbols(code.id, "getId") == []
    # References are linked afresh: the import from the changed file still resolves, the removed type doesn't
    assert where(store.usages(find(store, code, "format")), RESOLVED) == ["App.jsx:5", "UserCard.tsx:9"]


def test_windows_line_endings_and_encodings(store, tmp_path):
    root = tmp_path / "win"
    root.mkdir()
    source = "package p;\r\npublic class A {\r\n    void run() { }\r\n}\r\n"
    (root / "A.java").write_bytes(b"\xef\xbb\xbf" + source.encode("utf-8"))          # UTF-8 with a byte-order mark
    (root / "B.java").write_bytes(source.replace("A", "B").encode("utf-16"))             # UTF-16
    codebase = store.add(str(root))
    store.index(codebase.id)
    for name in ("A", "B"):
        run = next(s for s in store.search_symbols(codebase.id, "run") if s.qualified == f"p.{name}#run")
        assert run.line == 3 and store.lines(run.file_id)[2] == "    void run() { }"
    assert not any(f.has_errors for f in store.files(codebase.id))


def test_a_missing_folder_is_reported(store, code, tmp_path):
    with pytest.raises(ValueError):
        store.add(str(tmp_path / "nowhere"))
    with pytest.raises(ValueError):
        store.add(code.root)                      # Already registered
    shutil.rmtree(code.root)
    with pytest.raises(ValueError):
        store.index(code.id)
    store.remove(code.id)
    assert store.list_codebases() == [] and store.conn.execute("SELECT COUNT(*) FROM code_text").fetchone()[0] == 0


# ---- Symbols and search ------------------------------------------------------------------------

def test_symbols(store, code):
    save = find(store, code, "com.acme.service.UserService#save", params=2)
    assert (save.kind, save.path.rsplit("/", 1)[-1], save.line) == ("method", "UserService.java", 22)
    assert save.signature == "public void save(User user, boolean notify)"
    assert [s.name for s in store.search_symbols(code.id, "user", kinds=("class",))] == ["User", "UserService", "UserController"]
    card = find(store, code, "UserCard")
    assert card.kind == "function" and card.exported
    outline = [(s.kind, s.name) for s in store.outline(card.file_id)]
    assert outline == [("function", "UserCard"), ("function", "show")]
    assert store.symbol_at(save.file_id, 23).id == save.id


def test_text_search_finds_any_piece_in_any_case(store, code):
    hits = store.search_text(code.id, "/API/users")
    assert {(f.path.rsplit("/", 1)[-1], line) for f, line, _ in hits} == {
        ("UserController.java", 9), ("users.ts", 6), ("users.ts", 10), ("users.ts", 13), ("server.js", 4),
        ("UserCard.tsx", 2), ("UserCard.tsx", 3)}                                   # …and the imports of api/users
    assert [line for _, line, _ in store.search_text(code.id, "id")][:1]          # Under three characters still works


# ---- Usages ------------------------------------------------------------------------------------

def test_java_usages_follow_types_overloads_and_supertypes(store, code):
    one, two = (find(store, code, "com.acme.service.UserService#save", params=n) for n in (1, 2))
    assert where(store.usages(two), RESOLVED) == ["UserController.java:25"]         # save(user, true): the overload
    assert where(store.usages(one), RESOLVED) == ["UserService.java:23"]
    assert where(store.usages(one), BY_NAME) == ["UserController.java:26"]          # unknownThing().save(user)

    implementation = find(store, code, "com.acme.service.UserService#find")
    assert where(store.usages(implementation), SUPERTYPE) == ["UserController.java:20"]   # Called through Repository
    user = find(store, code, "com.acme.model.User")
    assert "UserController.java:19" in where(store.usages(user), RESOLVED)
    constructor = find(store, code, "com.acme.model.User#User")
    assert where(store.usages(constructor)) == ["UserController.java:20"]
    assert where(store.usages(find(store, code, "com.acme.model.User#getId")), BY_NAME) == ["UserService.java:13"]


def test_script_usages_follow_imports_aliases_and_require(store, code):
    fetch_user = find(store, code, "fetchUser")
    assert where(store.usages(fetch_user), RESOLVED) == ["UserCard.tsx:7"]          # Imported through the "@/" alias
    assert where(store.usages(find(store, code, "createUser")), RESOLVED) == ["UserCard.tsx:8"]   # users.createUser
    assert where(store.usages(find(store, code, "format")), RESOLVED) == ["App.jsx:5", "UserCard.tsx:9"]
    assert where(store.usages(find(store, code, "UserCard")), RESOLVED) == ["App.jsx:5"]   # <UserCard/>
    assert where(store.usages(find(store, code, "App#helper"))) == ["App.jsx:5"]
    assert "UserCard.tsx:12" in where(store.usages(find(store, code, "User")))


def test_calls_and_hierarchy(store, code):
    create = find(store, code, "com.acme.web.UserController#create")
    callees = sorted((u.name, u.target_id is not None) for u in store.callees(create))
    assert callees == [("save", False), ("save", True), ("unknownThing", False)]
    save = find(store, code, "com.acme.service.UserService#save", params=1)
    audit = find(store, code, "com.acme.service.UserService#audit")
    tree = store.call_tree(audit, callers=True)
    assert [n.symbol.id for n in tree] == [save.id]
    assert [n.symbol.qualified for n in tree[0].children] == ["com.acme.service.UserService#save"]   # save(user, notify)
    assert [n.symbol.qualified for n in tree[0].children[0].children] == ["com.acme.web.UserController#create"]
    assert [n.symbol.name for n in store.call_tree(save, callers=False)] == ["audit"]

    repository = find(store, code, "com.acme.service.Repository")
    assert [s.name for s in store.hierarchy(repository).subtypes] == ["UserService"]
    service = find(store, code, "com.acme.service.UserService")
    assert [s.name for s in store.hierarchy(service).supertypes] == ["Repository"]
    assert [s.qualified for s in store.hierarchy(save).overrides] == ["com.acme.service.Repository#save"]


# ---- Dependencies ------------------------------------------------------------------------------

def test_declared_and_used_libraries(store, code):
    declared = {d.name: d for d in store.declared(code.id)}
    assert set(declared) == {"org.springframework:spring-web", "junit:junit", "com.google.guava:guava",
                             "org.mockito:mockito-core", "axios", "react", "left-pad", "typescript"}
    assert declared["junit:junit"].scope == "test" and declared["typescript"].scope == "dev"
    assert (declared["axios"].used_in, declared["left-pad"].used_in) == (1, 0)      # left-pad: declared, never imported
    assert declared["org.springframework:spring-web"].used_in is None

    packages = {name: (files, uses) for name, files, uses in store.external_packages(code.id)}
    assert packages["java.util"][0] == 2 and packages["axios"] == (1, 2) and "express" in packages
    assert dict(store.external_members(code.id, "axios")) == {"axios#get": 1, "axios#post": 1}
    assert ("java.util.List#add", 1) in store.external_members(code.id, "java.util")
    assert dict(store.external_members(code.id, "org.springframework.web.bind.annotation"))[
        "org.springframework.web.bind.annotation.GetMapping"] == 1
    assert where(store.external_usages(code.id, "axios#get")) == ["users.ts:6"]
    assert [row["path"].rsplit("/", 1)[-1] for row in store.package_imports(code.id, "react")] == ["UserCard.tsx"]


def test_internal_dependencies(store, code):
    edges = {(a, b): n for a, b, n in store.internal_dependencies(code.id)}
    assert edges[("com.acme.web", "com.acme.service")] >= 4 and ("com.acme.model", "com.acme.web") not in edges
    assert ("frontend/src/components", "frontend/src/api") in edges
    links = store.package_links(code.id, "com.acme.service", "com.acme.model")
    assert links and all(u.path.startswith("backend/src/main/java/com/acme/service/") for u in links)
    card = find(store, code, "UserCard")
    assert [row["path"].rsplit("/", 1)[-1] for row in store.imported_by(card.file_id)] == ["App.jsx"]
    assert [row["target_path"] or row["external"] for row in store.imports_of(card.file_id)] == [
        "react", "frontend/src/api/users.ts", "frontend/src/api/users.ts", "frontend/src/util.js"]


# ---- Endpoints ---------------------------------------------------------------------------------

def test_endpoints_join_the_front_end_to_the_back_end(store, code):
    served, unmatched = store.endpoints(code.id)
    routes = {(s.method, s.path): [f"{c.file_path.rsplit('/', 1)[-1]}:{c.line}" for c in calls] for s, calls in served}
    assert routes == {
        ("GET", "/api/users/{id}"): ["users.ts:6"],
        ("POST", "/api/users"): ["users.ts:10"],
        ("GET", "/health"): [],
        ("DELETE", "/api/users/:id/avatar"): ["users.ts:13"],
    }
    assert unmatched == []
    handler = next(s for s, _ in served if s.path == "/api/users/{id}")
    assert handler.symbol_name == "com.acme.web.UserController#get" and handler.framework == "spring"


def test_path_matching():
    assert normalize_path("https://host:8080/api/users/${id}?x=1") == "/api/users/{}"
    assert normalize_path("{}/users/:id/") == "/users/{}"
    assert paths_match("/api/users/{}", "/users/{}") and paths_match("/users/{}", "/ctx/users/42")
    assert not paths_match("/api/users", "/api/orders") and not paths_match("/users", "/api/users")
    assert not paths_match("/api/{}", "/x/y/z/{}")


# ---- Parsing details ---------------------------------------------------------------------------

def test_java_parsing_details():
    parsed = parse("A.java", b"""package p;
import static java.util.Objects.requireNonNull;
public class A<T> extends Base<T> {
    @Path("/things") static class R { @GET @Path("{id}") public T one() { return null; } }
    private Map<String, List<T>> index;
    void run(Helper h) { h.go(1, 2); requireNonNull(h); Helper.make().go(); new Thread(this::run).start(); }
}""")
    refs = {(r.kind, r.name, r.receiver, r.args) for r in parsed.refs}
    assert ("call", "go", "Helper", 2) in refs and ("call", "make", "Helper", 0) in refs
    assert ("call", "requireNonNull", "this", 1) in refs and ("call", "run", "this", -1) in refs
    assert ("extends", "Base", "", -1) in refs and not any(r.name == "T" for r in parsed.refs)   # T is a type parameter
    assert [(e.method, e.path, e.framework) for e in parsed.endpoints] == [("GET", "/things/{id}", "jax-rs")]
    assert parsed.imports[0].static and parsed.package == "p"


def test_script_parsing_details():
    parsed = parse("a.js", b"""
const svc = { list() { return $.ajax({url: '/api/items', type: 'put'}); }, one: (id) => http.get(base + '/x') };
exports.go = function (a, b) { return new Thing(a); };
class Broken extends (
""")
    assert parsed.has_errors                                                # Still read as far as possible
    assert {s.qualified for s in parsed.symbols} >= {"svc", "svc#list", "svc#one", "go"}
    assert [(e.side, e.method, e.path) for e in parsed.endpoints] == [("client", "PUT", "/api/items")]
    assert ("new", "Thing", 1) in {(r.kind, r.name, r.args) for r in parsed.refs}


def test_manifests():
    assert manifests.read_manifest("package.json", "{not json") == []
    assert manifests.read_aliases('{ /* c */ "compilerOptions": {"baseUrl": "src", "paths": {"~/*": ["lib/*"],},}, }') \
        == ("src", {"~/*": ["lib/*"]})
    gradle = manifests.read_manifest("build.gradle.kts", 'dependencies { api(group = "a.b", name = "c", version = "1") }')
    assert gradle == [("gradle", "a.b:c", "1", "api")]
