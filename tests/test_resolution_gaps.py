"""
Closing the resolution gap (ADR-024), on tests/codebase_generics: type arguments bound through
supertypes, callback parameters typed from their receiver, a framework's repository members as a
rule, and `.d.ts` files of declared packages read as library symbols.

Each gap is a strict expected failure until it is closed, which keeps this file an honest list
(ADR-010's way). The last test guards every link the other fixtures had before the work: a link may
be added or go from by-name to resolved, never change from one resolved target to another.
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.code.store import CodeStore

GAP = pytest.mark.xfail(strict=True, reason="ADR-024: not built yet")

GENERICS = Path(__file__).parent / "codebase_generics"
BASELINE = Path(__file__).parent / "baseline" / "links_before_adr_024.json"


def _store(root: Path, name: str):
    """Indexed with the JDK and jars left unread: the fixture's node_modules are read, the machine's libraries are not."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(root), name)
    previous = os.environ.get("SEARCHABLES_LIBRARIES")
    os.environ["SEARCHABLES_LIBRARIES"] = "0"
    try:
        store.index(codebase.id)
    finally:
        if previous is None:
            del os.environ["SEARCHABLES_LIBRARIES"]
        else:
            os.environ["SEARCHABLES_LIBRARIES"] = previous
    return store, codebase


@pytest.fixture(scope="module")
def generics():
    return _store(GENERICS, "Generics")


def ref(store, codebase, path_end, line, name, col=None):
    """The reference to `name` on a line: (target symbol's qualified name or None, outside target, via)."""
    rows = store.conn.execute(
        "SELECT r.target_id, r.target, r.col, r.via, s.qualified FROM code_refs r JOIN code_files f ON f.id = r.file_id "
        "LEFT JOIN code_symbols s ON s.id = r.target_id "
        "WHERE f.codebase_id = ? AND f.path LIKE ? AND r.line = ? AND r.name = ? AND r.kind = 'call' ORDER BY r.col",
        (codebase.id, "%" + path_end, line, name)).fetchall()
    assert rows, f"no call of {name} at {path_end}:{line}"
    row = rows[0] if col is None else next(r for r in rows if r["col"] == col)
    return row["qualified"], row["target"], row["via"]


# ---- Java: type arguments through supertypes ------------------------------------------------------

def test_java_supertype_binding_types_what_a_repository_returns(generics):
    """ItemRepository extends BaseRepository<Item, Long>: findById gives Optional<Item>, so the chain goes on."""
    store, codebase = generics
    assert ref(store, codebase, "ItemService.java", 23, "getSupplier")[0] == "com.store.model.Item#getSupplier"
    assert ref(store, codebase, "ItemService.java", 23, "getName")[0] == "com.store.model.Supplier#getName"


def test_java_generic_base_class_member_is_bound_in_the_subclass(generics):
    """SupplierService extends BaseService<Supplier>: load(id) is a Supplier."""
    store, codebase = generics
    assert ref(store, codebase, "SupplierService.java", 10, "getName")[0] == "com.store.model.Supplier#getName"


def test_java_second_type_variable_of_a_map(generics):
    """Map<String, Item>.get gives the value type, the second variable, not the first."""
    store, codebase = generics
    assert ref(store, codebase, "ItemService.java", 27, "getCode")[0] == "com.store.model.Item#getCode"


# ---- Java: callbacks typed from the receiver --------------------------------------------------------

def test_java_stream_callbacks_are_typed_and_map_carries_the_body_type(generics):
    store, codebase = generics
    assert ref(store, codebase, "ItemService.java", 32, "getSupplier")[0] == "com.store.model.Item#getSupplier"
    assert ref(store, codebase, "ItemService.java", 33, "getName")[0] == "com.store.model.Supplier#getName"   # After map(i -> i.getSupplier())
    assert ref(store, codebase, "ItemService.java", 34, "getName")[0] == "com.store.model.Supplier#getName"


def test_java_optional_and_iterable_callbacks(generics):
    store, codebase = generics
    assert ref(store, codebase, "ItemService.java", 39, "getCode")[0] == "com.store.model.Item#getCode"   # ifPresent
    assert ref(store, codebase, "ItemService.java", 40, "getId")[0] == "com.store.model.Item#getId"       # forEach


# ---- Java: a framework's repository members as a rule ---------------------------------------------

def test_spring_data_members_link_by_rule_when_no_jar_is_read(generics):
    """StoredItemRepository extends JpaRepository<Item, Long> and the jar isn't on disk: count and findById come from the rule."""
    store, codebase = generics
    qualified, target, via = ref(store, codebase, "ItemService.java", 44, "count")
    assert qualified is None and target == "org.springframework.data.repository.CrudRepository#count" and via == "rule"
    assert ref(store, codebase, "ItemService.java", 48, "findById")[1] == "org.springframework.data.repository.CrudRepository#findById"
    assert ref(store, codebase, "ItemService.java", 48, "getCode")[0] == "com.store.model.Item#getCode"   # Optional<Item> bound by the rule


# ---- TypeScript: declaration files, callbacks, bindings ------------------------------------------

def test_dts_members_type_a_chain_through_a_deep_import_and_explicit_type_arguments(generics):
    """HttpClient.get<T> from @acme/http/client gives Observable<T>; subscribe's callback receives an Item."""
    store, codebase = generics
    assert ref(store, codebase, "api.ts", 9, "get")[1] == "@acme/http#HttpClient.get"
    assert ref(store, codebase, "api.ts", 9, "rating")[0] == "Supplier#rating"


def test_ts_array_callbacks_and_map_result(generics):
    store, codebase = generics
    assert ref(store, codebase, "api.ts", 13, "rating")[0] == "Supplier#rating"


def test_dts_generic_interface_bound_through_a_function_s_type_argument(generics):
    """request<PageOf<Item>> gives Promise<Page<Item>>; await, then first() is an Item."""
    store, codebase = generics
    assert ref(store, codebase, "api.ts", 18, "first")[1] == "@acme/http#PageOf.first"   # Its exported name
    assert ref(store, codebase, "api.ts", 18, "rating")[0] == "Supplier#rating"


def test_dom_and_es5_declarations_type_fetch_and_then(generics):
    store, codebase = generics
    assert ref(store, codebase, "api.ts", 22, "json")[1] == "#Response.json"


def test_ts_generic_class_bound_in_the_subclass(generics):
    store, codebase = generics
    assert ref(store, codebase, "widget.ts", 13, "rating")[0] == "Supplier#rating"


def test_interface_properties_are_members(generics):
    """An interface's properties are fields of the type, so chains go through them."""
    store, codebase = generics
    supplier = next(s for s in store.search_symbols(codebase.id, "supplier") if s.qualified == "Item#supplier")
    assert supplier.kind == "field" and supplier.type == "Supplier"


def test_declared_packages_are_listed_as_libraries(generics):
    store, codebase = generics
    paths = [row["path"] for row in store.libraries(codebase.id)]
    assert any(p.endswith("node_modules/@acme/http") for p in paths) and any(p.endswith("typescript/lib") for p in paths)
    languages = {row["language"] for row in store.conn.execute("SELECT DISTINCT language FROM code_library")}
    assert languages == {"typescript"}


# ---- No regression on the other fixtures ----------------------------------------------------------

@pytest.mark.parametrize("name", ["codebase", "codebase_examples"])
def test_links_of_the_other_fixtures_only_improve(name):
    def by_line(links):   # A reference is known by its line, kind and name (its column moved for member calls, to the member's name)
        grouped = {}
        for key, target in links.items():
            path, line, _, kind, name = key.rsplit(":", 4)
            grouped.setdefault(f"{path}:{line}:{kind}:{name}", []).append(target)
        return grouped
    before = by_line(json.loads(BASELINE.read_text())[name])
    store, codebase = _store(Path(__file__).parent / name, name)
    after = {}
    for r in store.conn.execute(
            "SELECT r.*, f.path, s.qualified AS tq FROM code_refs r JOIN code_files f ON f.id = r.file_id "
            "LEFT JOIN code_symbols s ON s.id = r.target_id WHERE r.codebase_id = ?", (codebase.id,)):
        after[f"{r['path']}:{r['line']}:{r['col']}:{r['kind']}:{r['name']}"] = ("=" + r["tq"]) if r["tq"] else (r["target"] or None)
    after = by_line(after)
    missing = [key for key in before if key not in after or len(after[key]) != len(before[key])]
    assert not missing, f"references that disappeared: {missing}"
    changed = {key: (old, after[key]) for key, old in before.items()
               if any(t is not None and t not in after[key] for t in old)}
    assert not changed, f"links that changed target: {changed}"
