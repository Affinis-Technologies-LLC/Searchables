"""The change-impact view (ADR-018): the closure over callers, grouped by layer, with routes and tests reached."""
import sqlite3
from pathlib import Path

import pytest

from src.code.impact import impact_of
from src.code.store import CodeStore
from tests.test_examples import SAMPLE


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    conn = sqlite3.connect(tmp_path_factory.mktemp("shop") / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(SAMPLE), "Shop")
    store.index(codebase.id)
    return store, codebase


def symbol(store, codebase, qualified, params=None):
    return next(s for s in store.search_symbols(codebase.id, qualified.split("#")[-1]) if s.qualified == qualified and (params is None or s.params == params))


def test_the_closure_over_callers_with_routes_and_tests(shop):
    store, codebase = shop
    save = symbol(store, codebase, "com.shop.repo.OrderRepository#save", params=1)
    impact = impact_of(store, save)
    names = {n.qualified.split(".")[-1]: n for n in impact.nodes}
    assert set(names) == {"OrderService#place", "OrderController#create", "OrderServiceTest#savesAnOrder"}
    assert names["OrderService#place"].depth == 1 and names["OrderController#create"].depth == 2
    assert all(n.certainty == "resolved" for n in impact.nodes)
    assert [r.route for r in impact.routes] == ["POST /api/orders"] and impact.routes[0].handler.endswith("#create")
    assert [t.path.rsplit("/", 1)[-1] for t in impact.tests] == ["OrderServiceTest.java"]
    assert [g.layer for g in impact.layers] == ["com.shop.web", "com.shop.service"]
    assert not impact.truncated and impact.by_name_included is False


def test_a_type_reaches_through_its_members(shop):
    store, codebase = shop
    audit = symbol(store, codebase, "com.shop.service.Audit")
    impact = impact_of(store, audit)
    reached = {n.qualified.split(".")[-1] for n in impact.nodes}
    assert {"OrderService#place", "OrderService#cancel", "CustomerService#register", "OrderController#create"} <= reached
    assert {"OrderService", "CustomerService"} <= reached    # The field initialisers `new Audit()` are in the classes themselves


def test_by_name_edges_only_when_asked(shop):
    store, codebase = shop
    get_id = symbol(store, codebase, "com.shop.model.Order#getId")
    linked = impact_of(store, get_id)
    loose = impact_of(store, get_id, by_name=True)
    assert len(loose.nodes) >= len(linked.nodes) and loose.by_name_included
    assert all(n.certainty == "resolved" for n in linked.nodes)
    # find's lambda `o -> o.getId()` is a by-name use: it appears only when asked, marked as such
    assert any(n.qualified.endswith("OrderRepository#find") and n.certainty == "name" for n in loose.nodes)
    assert not any(n.qualified.endswith("OrderRepository#find") for n in linked.nodes)


def test_bounds_are_reported(shop):
    store, codebase = shop
    save = symbol(store, codebase, "com.shop.repo.OrderRepository#save", params=1)
    impact = impact_of(store, save, max_nodes=1)
    assert impact.truncated and len(impact.nodes) == 1
