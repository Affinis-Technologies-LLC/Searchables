"""Index snapshots, diffed (ADR-020)."""
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.code.snapshots import diff_against, take_snapshot
from src.code.store import CodeStore
from tests.test_examples import SAMPLE


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return CodeStore(conn)


def edit(root: Path) -> None:
    service = root / "backend/src/main/java/com/shop/service/OrderService.java"
    text = service.read_text()
    text = text.replace("public Order load(long id)", "public Order load(String id)")          # Changed signature
    text = text.replace("    public List<Order> open() {", "    public int pending() { return 0; }\n\n    public List<Order> open() {")   # Added
    text = text.replace("""    public void cancel(long id) {
        Order order = repository.find(id).orElse(null);
        if (order != null) {
            order.setStatus("cancelled");
            repository.save(order, true);
            audit.record("cancel", id);
        }
    }

""", "")                                                                                         # Removed
    service.write_text(text)
    audit = root / "backend/src/main/java/com/shop/service/Audit.java"
    (root / "backend/src/main/java/com/shop/util").mkdir()
    (root / "backend/src/main/java/com/shop/util/Audit.java").write_text(audit.read_text().replace("package com.shop.service;", "package com.shop.util;"))
    audit.unlink()                                                                               # Moved (and its package changed)
    for name in ("OrderService.java", "CustomerService.java"):
        f = root / "backend/src/main/java/com/shop/service" / name
        f.write_text(f.read_text().replace("package com.shop.service;", "package com.shop.service;\n\nimport com.shop.util.Audit;"))


def test_a_snapshot_diffed_against_the_edited_index(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "shop")
    codebase = store.add(str(tmp_path / "shop"), "Shop")
    store.index(codebase.id)
    snapshot = take_snapshot(store, codebase.id, "before")
    assert snapshot.symbol_count > 40 and snapshot.label == "before"
    edit(tmp_path / "shop")
    store.index(codebase.id)
    d = diff_against(store, codebase.id, snapshot_id=snapshot.id)
    short = lambda s: s.qualified.split(".")[-1]
    assert [short(s) for s in d.added if "Audit" not in s.qualified] == ["OrderService#pending"]
    assert [short(s) for s in d.removed if "Audit" not in s.qualified] == ["OrderService#cancel"]
    assert [(short(c.now), c.before_signature.split("(")[1]) for c in d.changed] == [("OrderService#load", "long id)")]
    assert d.changed[0].now.signature.endswith("load(String id)")
    assert {short(c.now) for c in d.changed} == {"OrderService#load"}
    assert [c.now.qualified for c in d.moved] == []                                      # Audit changed package: removed + added by identity, not moved
    assert "Audit" in {s.name for s in d.added} and "Audit" in {s.name for s in d.removed}
    # Callers affected: load is called by the controller; cancel had no callers; the removed Audit#record had three
    assert [u.from_name.split(".")[-1] for u in d.changed[0].callers] == ["OrderController#get"]
    record = next(s for s in d.removed if s.name == "record")
    assert d.removed_callers[record.qualified] >= 3
    assert d.by_name_before <= d.by_name_now                                             # Nothing got more certain by the edit


def test_two_codebases_diffed(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "a")
    shutil.copytree(SAMPLE, tmp_path / "b")
    edit(tmp_path / "b")
    a = store.add(str(tmp_path / "a"), "A")
    b = store.add(str(tmp_path / "b"), "B")
    store.index(a.id)
    store.index(b.id)
    d = diff_against(store, b.id, codebase_id_before=a.id)
    assert [s.qualified.split(".")[-1] for s in d.added] == ["OrderService#pending"] or "Audit" in {s.name for s in d.added}
    assert any(s.qualified.endswith("OrderService#cancel") for s in d.removed)
    assert [c.now.qualified.split(".")[-1] for c in d.changed] == ["OrderService#load"]


def test_snapshots_are_listed_and_deleted(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "shop")
    codebase = store.add(str(tmp_path / "shop"), "Shop")
    store.index(codebase.id)
    first = take_snapshot(store, codebase.id, "one")
    second = take_snapshot(store, codebase.id, "two")
    assert [s.label for s in store.snapshots(codebase.id)] == ["one", "two"]
    store.delete_snapshot(first.id)
    assert [s.id for s in store.snapshots(codebase.id)] == [second.id]
    d = diff_against(store, codebase.id, snapshot_id=second.id)
    assert not d.added and not d.removed and not d.changed and not d.moved
