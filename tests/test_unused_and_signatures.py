"""Dead and unreachable code, and signature-aware search (ADR-019)."""
import sqlite3
from pathlib import Path

import pytest

from src.code.signatures import search_signatures
from src.code.store import CodeStore
from src.code.unused import unused_in

SHOP = Path(__file__).parent / "codebase_examples"
WEB = Path(__file__).parent / "codebase_web"


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    conn = sqlite3.connect(tmp_path_factory.mktemp("shop") / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(SHOP), "Shop")
    store.index(codebase.id)
    return store, codebase


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    conn = sqlite3.connect(tmp_path_factory.mktemp("web") / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(WEB), "Web")
    store.index(codebase.id)
    return store, codebase


def short(symbol):
    return symbol.qualified.split(".")[-1]


def test_methods_nothing_calls(shop):
    store, codebase = shop
    unused = unused_in(store, codebase.id)
    methods = sorted(short(u.symbol) for u in unused.methods if u.symbol.language == "java")
    # Never called anywhere; Repository#count and its overrides included; the OrderController handlers are routes, the test is a test
    assert methods == ["Customer#getName", "CustomerRepository#count", "CustomerService#lookup", "CustomerService#register",
                       "Order#getStatus", "OrderRepository#count", "OrderService#cancel", "OrderService#open", "Repository#count"]
    functions = sorted(u.symbol.name for u in unused.methods if u.symbol.language == "typescript")
    assert functions == ["createOrder", "fetchCustomer", "fetchOrder", "legacyLookup", "registerCustomer", "useOrders"]   # Exported, imported nowhere
    assert all(u.certainty == "none" for u in unused.methods)
    handlers = {short(u.symbol) for u in unused.methods}
    assert "OrderController#get" not in handlers and "OrderServiceTest#savesAnOrder" not in handlers
    assert "Order#setStatus" not in handlers      # Called in cancel
    assert "OrderService#validate" not in handlers   # Called by place


def test_only_by_name_references_are_listed_apart(shop):
    store, codebase = shop
    unused = unused_in(store, codebase.id)
    # getId is called for certain in place/validate/register, and by name in the lambdas: used, not listed
    assert not any(short(u.symbol).endswith("#getId") for u in unused.methods + unused.by_name_only)
    assert all(u.certainty == "name" and u.by_name_references > 0 for u in unused.by_name_only)


def test_routes_types_and_exports(shop, web):
    store, codebase = shop
    unused = unused_in(store, codebase.id)
    assert unused.routes == []                                   # Both routes are reached by the TypeScript side's http calls
    assert {short(t.symbol) for t in unused.types} == {"CustomerService"}   # Nothing constructs it or calls its methods
    store, codebase = web
    unused = unused_in(store, codebase.id)
    exports = sorted(e.symbol.qualified for e in unused.exports)
    assert "AppModule" in exports                      # Exported, imported by nothing (the Angular bootstrap is outside the codebase)
    assert "UserListComponent" not in exports          # Declared by the module, used by a template
    assert "App" in exports                            # The React root is rendered by an entry file outside the fixture


def test_signature_search(shop):
    store, codebase = shop
    found = search_signatures(store, codebase.id, kind="method", param="Order", returns="")
    assert sorted(short(s) for s in found) == ["OrderController#create", "OrderRepository#save", "OrderRepository#save", "OrderService#place", "OrderService#validate"]
    found = search_signatures(store, codebase.id, kind="method", returns="Optional")
    assert sorted(short(s) for s in found) == ["CustomerRepository#find", "OrderRepository#find"]
    found = search_signatures(store, codebase.id, returns="Optional", param="long")
    assert sorted(short(s) for s in found) == ["CustomerRepository#find", "OrderRepository#find"]
    found = search_signatures(store, codebase.id, kind="field", returns="Audit")
    assert sorted(short(s) for s in found) == ["CustomerService#audit", "OrderService#audit"]
    found = search_signatures(store, codebase.id, owner="OrderRepository", params=2)
    assert [short(s) for s in found] == ["OrderRepository#save"]
    found = search_signatures(store, codebase.id, kind="function", returns="Promise")
    assert {s.name for s in found} >= {"fetchOrder", "createOrder", "fetchCustomer"}
    assert search_signatures(store, codebase.id, returns="Nothing") == []
