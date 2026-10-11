"""Convention checks from mined patterns (ADR-021): findings on the fixtures equal a hand-made list."""
import sqlite3
from pathlib import Path

import pytest

from src.code.checks import checks_for
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


def test_findings_on_the_fixture(shop):
    store, codebase = shop
    findings = checks_for(store, codebase.id)
    by_kind = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    # record goes with save in 3 of 3 methods; the test method saves without recording: save goes with record only 3 of 4 (< 0.8), so no finding there
    assert "companion" not in by_kind or all(f.symbol.qualified != "com.shop.service.OrderServiceTest#savesAnOrder" for f in by_kind["companion"])
    # Naming: com.shop.repo types all end in Repository (3 of 3); com.shop.service has Service in 2 of 3: fewer than three share it, no finding
    assert "naming" not in by_kind
    # Errors: only IllegalArgumentException is thrown; no one-off
    assert "error" not in by_kind
    assert all(f.examples for f in findings) and all(0 < f.confidence <= 1 for f in findings)


def test_a_missing_companion_is_found(shop, tmp_path):
    import shutil
    shutil.copytree(SAMPLE, tmp_path / "shop")
    service = tmp_path / "shop/backend/src/main/java/com/shop/service/OrderService.java"
    service.write_text(service.read_text().replace("    public List<Order> open() {", """    public void archive(Order order) {
        audit.record("archive", order.getId());
    }

    public void reopen(Order order) {
        repository.save(order);
        audit.record("reopen", order.getId());
    }

    public void hold(Order order) {
        repository.save(order);
        audit.record("hold", order.getId());
    }

    public List<Order> open() {"""))
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(tmp_path / "shop"), "Shop2")
    store.index(codebase.id)
    findings = [f for f in checks_for(store, codebase.id) if f.kind == "companion"]
    assert [f.symbol.qualified.split(".")[-1] for f in findings] == ["OrderService#archive"]
    assert "record" in findings[0].message and "save" in findings[0].message and findings[0].confidence >= 0.8
    assert {e.enclosing.split("#")[-1] for e in findings[0].examples} == {"place", "cancel", "register", "reopen", "hold"}
    assert findings[0].line == 14 or findings[0].line > 0
    per_file = checks_for(store, codebase.id, file_id=findings[0].file_id)
    assert [f.kind for f in per_file] == ["companion"]
