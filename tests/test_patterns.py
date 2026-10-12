"""The Patterns view (ADR-013): counts mined from the index, each equal to a hand count on the fixtures."""
import sqlite3
from pathlib import Path

import pytest

from src.code.patterns import patterns_for
from src.code.store import CodeStore

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
    return store, patterns_for(store, codebase.id)


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    conn = sqlite3.connect(tmp_path_factory.mktemp("web") / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(WEB), "Web")
    store.index(codebase.id)
    return store, patterns_for(store, codebase.id)


def test_idioms_per_type_are_ordered_pairs_of_calls_within_a_method(shop):
    _, p = shop
    repo = next(t for t in p.idioms if t.type_name == "OrderRepository")
    # OrderRepository is called in place (save), load (find), cancel (find then save), open (all), savesAnOrder (save then find)
    assert repo.call_sites == 7
    assert {(i.first, i.second, i.methods) for i in repo.pairs} == {("find", "save", 1), ("save", "find", 1)}
    assert {m.name: m.calls for m in repo.members} == {"find": 3, "save": 3, "all": 1}


def test_how_things_are_made(shop):
    _, p = shop
    made = {m.type_name: m for m in p.made}
    # OrderRepository: constructed with new in OrderService and OrderServiceTest (as field initialisers); never injected; no factory
    assert (made["OrderRepository"].constructed, made["OrderRepository"].injected, made["OrderRepository"].factory) == (2, 0, 0)
    # Order: new Order(7) in the test, new Order(id)? no; returned by load (factory-like) and by find's Optional; fields typed Order: none
    assert made["Order"].constructed == 1
    assert made["Audit"].constructed == 2 and made["Audit"].injected == 0
    assert all(m.examples for m in p.made)


def test_pairs_that_go_together(shop):
    _, p = shop
    pairs = {(a.split("#")[-1], b.split("#")[-1]): (support, confidence) for a, b, support, confidence in
             [(x.first, x.second, x.support, x.confidence) for x in p.pairs]}
    # Audit.record goes with a repository save in place, cancel and register: 3 methods, every record has a save
    assert pairs[("record", "save")] == (3, 1.0) or pairs[("save", "record")] == (3, 1.0)
    assert all(x.support >= 3 and x.confidence >= 0.8 for x in p.pairs)


def test_entry_points_and_layers(shop):
    _, p = shop
    assert [e.route for e in p.entry_points] == ["GET /api/orders/{id}", "POST /api/orders"]
    get = p.entry_points[0]
    assert get.handler.endswith("OrderController#get")
    assert [n.symbol.split("#")[-1] for n in get.chain] == ["load"] and [c.symbol.split("#")[-1] for c in get.chain[0].children] == ["find"]
    assert p.layers[:3] == ["com.shop.web", "com.shop.service", "com.shop.repo"] and p.layers[-1] == "com.shop.model"


def test_hotspots(shop):
    _, p = shop
    assert [(h.qualified, h.references) for h in p.hot_symbols[:4]] == [("Http#get", 4), ("com.shop.model.Order#getId", 3), ("com.shop.repo.OrderRepository#find", 3),
                                                                        ("com.shop.service.Audit#record", 3)]   # getId: place, validate, and find's lambda (ADR-024)
    assert [(f.path.rsplit("/", 1)[-1], f.references) for f in p.hot_files[:2]] == [("Order.java", 18), ("OrderRepository.java", 11)]   # Types, calls and constructions from other files


def test_conventions(shop):
    _, p = shop
    suffixes = {(c.package, c.suffix): (c.count, c.total) for c in p.naming}
    assert suffixes[("com.shop.service", "Service")] == (2, 3)       # OrderService, CustomerService; Audit doesn't
    assert suffixes[("com.shop.repo", "Repository")] == (3, 3)
    assert p.test_folders == ["backend/src/test"]
    assert [(e.type_name, e.count) for e in p.errors] == [("IllegalArgumentException", 1)]   # throw new …; the orElseThrow lambda isn't a throw


def test_framework_views(web):
    _, p = web
    angular = {c.name: c for c in p.angular}
    user_list = angular["UserListComponent"]
    assert user_list.selector == "app-user-list" and user_list.template.endswith("user-list.component.html")
    assert user_list.inputs == ["title"] and user_list.outputs == ["selected"] and user_list.injected == ["UserService"]
    assert angular["AppComponent"].selector == "app-root" and angular["AppComponent"].template == "" and angular["AppComponent"].renders == ["UserListComponent"]
    react = {c.name: c for c in p.react}
    assert react["App"].renders == ["UserList"] and react["UserList"].renders == ["UserCard"]
    assert react["UserList"].hooks == ["useCallback", "useState", "useUsers"]
    assert react["UserCard"].hooks == [] and react["UserCard"].renders == []     # Rendered by UserList; uses no hooks


def test_every_pattern_opens_examples(shop):
    _, p = shop
    for group in (p.made, p.pairs, p.hot_symbols, p.naming, p.errors):
        for item in group:
            assert item.examples, item
    for idiom in p.idioms:
        assert all(m.examples for m in idiom.members) and all(pair.examples for pair in idiom.pairs)
