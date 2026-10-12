"""Git status, diff and commit; rename symbol with preview (ADR-015)."""
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.code import git
from src.code.rename import apply_rename, preview_rename
from src.code.store import CodeStore
from tests.test_examples import SAMPLE

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git isn't installed")


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "shop")
    root = tmp_path / "shop"
    subprocess.run([GIT, "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "."], cwd=root, check=True)
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "start"], cwd=root, check=True)
    return root


@needs_git
def test_status_diff_and_commit(repo):
    assert git.info(repo).repository and git.info(repo).branch == "main" and git.info(repo).entries == []
    service = repo / "backend/src/main/java/com/shop/service/OrderService.java"
    service.write_text(service.read_text().replace("audit.record(\"place\"", "audit.record(\"placed\""))
    (repo / "NOTES.md").write_text("notes\n")
    info = git.info(repo)
    assert [(e.path, e.status) for e in info.entries] == [("NOTES.md", "??"), ("backend/src/main/java/com/shop/service/OrderService.java", " M")]
    diff = git.diff(repo, "backend/src/main/java/com/shop/service/OrderService.java")
    assert '-        audit.record("place"' in diff and '+        audit.record("placed"' in diff
    result = git.commit(repo, ["backend/src/main/java/com/shop/service/OrderService.java"], "Rename the audit event")
    assert result.committed and result.commit
    assert [e.path for e in git.info(repo).entries] == ["NOTES.md"]
    log = git.log(repo)
    assert log[0].message == "Rename the audit event" and log[1].message == "start"
    with pytest.raises(ValueError):
        git.commit(repo, ["../outside"], "x")
    with pytest.raises(ValueError):
        git.commit(repo, ["NOTES.md"], "")
    assert not hasattr(git, "push")


def test_no_repository_is_reported(tmp_path):
    (tmp_path / "plain").mkdir()
    info = git.info(tmp_path / "plain")
    assert info.repository is False and info.entries == []


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return CodeStore(conn)


def test_rename_with_preview(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "shop")
    codebase = store.add(str(tmp_path / "shop"), "Shop")
    store.index(codebase.id)
    find = next(s for s in store.search_symbols(codebase.id, "find") if s.qualified == "com.shop.repo.OrderRepository#find")
    preview = preview_rename(store, find, "lookup")
    places = sorted((p.path.rsplit("/", 1)[-1], p.line, p.certainty, p.selected) for p in preview.edits)
    assert places == [("OrderRepository.java", 11, "declaration", True), ("OrderService.java", 18, "resolved", True),
                      ("OrderService.java", 22, "resolved", True), ("OrderServiceTest.java", 12, "resolved", True)]
    assert all(p.text[p.col - 1:p.col - 1 + 4] == "find" for p in preview.edits)
    assert preview.also == []                                    # Nothing overrides it

    result = apply_rename(store, find, "lookup", [p.key for p in preview.edits])
    assert sorted(f.path.rsplit("/", 1)[-1] for f in result.files) == ["OrderRepository.java", "OrderService.java", "OrderServiceTest.java"]
    assert result.skipped == []
    text = (tmp_path / "shop/backend/src/main/java/com/shop/service/OrderService.java").read_text()
    assert "repository.lookup(id)" in text and "repository.find(" not in text
    lookup = next(s for s in store.search_symbols(codebase.id, "lookup") if s.qualified == "com.shop.repo.OrderRepository#lookup")
    assert sorted(u.line for u in store.usages(lookup)) == [12, 18, 22]
    assert next(s for s in store.search_symbols(codebase.id, "find") if s.qualified == "com.shop.repo.CustomerRepository#find")   # Untouched


def test_rename_renames_overrides_together_and_skips_a_changed_place(store, tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "shop")
    codebase = store.add(str(tmp_path / "shop"), "Shop")
    store.index(codebase.id)
    count = next(s for s in store.search_symbols(codebase.id, "count") if s.qualified == "com.shop.repo.Repository#count")
    preview = preview_rename(store, count, "size")
    assert sorted(a.qualified for a in preview.also) == ["com.shop.repo.CustomerRepository#count", "com.shop.repo.OrderRepository#count"]
    declarations = [p for p in preview.edits if p.certainty == "declaration"]
    assert len(declarations) == 3
    # The file changes under us before applying: that place is skipped, the rest applied
    repo_file = tmp_path / "shop/backend/src/main/java/com/shop/repo/OrderRepository.java"
    repo_file.write_text(repo_file.read_text().replace("public int count()", "public int   count()"))
    result = apply_rename(store, count, "size", [p.key for p in preview.edits])
    assert [s.path.rsplit("/", 1)[-1] for s in result.skipped] == ["OrderRepository.java"]
    assert "int size()" in (tmp_path / "shop/backend/src/main/java/com/shop/repo/Repository.java").read_text()


# ---- Rename completeness (ADR-025) -----------------------------------------------------------------

WEB = SAMPLE.parent / "codebase_web"
GAP = pytest.mark.xfail(strict=True, reason="ADR-025: not built yet")


def _indexed(store, tmp_path, fixture, name="Copy", extra=None):
    root = tmp_path / name
    shutil.copytree(fixture, root)
    for relative, text in (extra or {}).items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text)
    codebase = store.add(str(root), name)
    store.index(codebase.id)
    return root, codebase


def _symbol(store, codebase, qualified, kind=None):
    return next(s for s in store.search_symbols(codebase.id, qualified.split("#")[-1].split(".")[-1])
                if s.qualified == qualified and (kind is None or s.kind == kind))


def _by_name(store, codebase, name, language):
    return store.conn.execute(
        "SELECT COUNT(*) FROM code_refs r JOIN code_files f ON f.id = r.file_id WHERE r.codebase_id = ? AND r.name = ? "
        "AND f.language = ? AND r.target_id IS NULL AND r.target IS NULL AND r.kind != 'annotation'", (codebase.id, name, language)).fetchone()[0]


def test_renaming_a_class_updates_imports_constructors_and_the_file(store, tmp_path):
    root, codebase = _indexed(store, tmp_path, SAMPLE, extra={
        "backend/src/main/java/com/shop/service/Names.java": 'package com.shop.service;\n\npublic class Names {\n    static final String KIND = "Order";\n}\n'})
    order = _symbol(store, codebase, "com.shop.model.Order", "class")
    usages_before = len([u for u in store.usages(order) if u.certainty == "resolved"])
    preview = preview_rename(store, order, "Purchase")
    places = {(p.path.rsplit("/", 1)[-1], p.line, p.certainty) for p in preview.edits}
    assert ("OrderRepository.java", 3, "resolved") in places and ("OrderService.java", 3, "resolved") in places   # import com.shop.model.Order;
    assert ("Order.java", 7, "declaration") in places                                                               # public Order(long id)
    assert sum(1 for p in preview.edits if p.path.endswith("OrderServiceTest.java") and p.line == 10) == 2          # Order order = new Order(7)
    assert preview.file_rename == ("backend/src/main/java/com/shop/model/Order.java", "backend/src/main/java/com/shop/model/Purchase.java")
    assert [(m.path.rsplit("/", 1)[-1], m.line) for m in preview.mentions] == [("Names.java", 4)]                    # "Order": a string, listed, not an edit
    assert all(not p.selected for p in preview.edits if p.certainty == "name")

    result = apply_rename(store, order, "Purchase", [p.key for p in preview.edits if p.selected], rename_file=True)
    assert (root / "backend/src/main/java/com/shop/model/Purchase.java").exists() and not (root / "backend/src/main/java/com/shop/model/Order.java").exists()
    assert "import com.shop.model.Purchase;" in (root / "backend/src/main/java/com/shop/service/OrderService.java").read_text()
    assert "new Purchase(7)" in (root / "backend/src/test/java/com/shop/service/OrderServiceTest.java").read_text()
    assert '"Order"' in (root / "backend/src/main/java/com/shop/service/Names.java").read_text()   # The mention stays
    store.index(codebase.id)
    assert _by_name(store, codebase, "Order", "java") == 0   # The compiler's check without a compiler
    purchase = _symbol(store, codebase, "com.shop.model.Purchase", "class")
    assert len([u for u in store.usages(purchase) if u.certainty == "resolved"]) == usages_before


def test_renaming_an_exported_function_updates_named_imports_but_not_aliases(store, tmp_path):
    root, codebase = _indexed(store, tmp_path, SAMPLE, extra={
        "frontend/src/hooks/useLater.ts": "import { fetchOrders as later } from '../api/orders';\n\nexport function useLater() { return later(); }\n"})
    fetch_orders = _symbol(store, codebase, "fetchOrders", "function")
    preview = preview_rename(store, fetch_orders, "loadOrders")
    places = {(p.path.rsplit("/", 1)[-1], p.line, p.certainty) for p in preview.edits}
    assert ("useOrders.ts", 2, "resolved") in places and ("useLater.ts", 1, "resolved") in places
    assert not any(p.path.endswith("useLater.ts") and p.line == 3 for p in preview.edits)   # later() keeps its local name
    assert preview.file_rename is None                                                       # A TypeScript file isn't tied to the name
    apply_rename(store, fetch_orders, "loadOrders", [p.key for p in preview.edits if p.selected])
    assert "import { loadOrders, Order }" in (root / "frontend/src/hooks/useOrders.ts").read_text()
    assert "import { loadOrders as later }" in (root / "frontend/src/hooks/useLater.ts").read_text()
    store.index(codebase.id)
    assert _by_name(store, codebase, "fetchOrders", "typescript") == 0


def test_field_accesses_are_references_and_are_renamed(store, tmp_path):
    root, codebase = _indexed(store, tmp_path, SAMPLE)
    status = _symbol(store, codebase, "com.shop.model.Order#status", "field")
    assert sorted((u.line, u.kind) for u in store.usages(status) if u.certainty == "resolved") == [(9, "use"), (10, "use")]   # return status; this.status = status
    preview = preview_rename(store, status, "state")
    assert sorted(p.line for p in preview.edits if p.path.endswith("Order.java")) == [5, 9, 10]
    assert sum(1 for p in preview.edits if p.line == 10) == 1   # The parameter `status` on that line is not the field
    apply_rename(store, status, "state", [p.key for p in preview.edits if p.selected])
    text = (root / "backend/src/main/java/com/shop/model/Order.java").read_text()
    assert "private String state;" in text and "return state;" in text and "this.state = status;" in text


def test_a_typescript_field_is_renamed_with_its_accesses_and_template_bindings(store, tmp_path):
    root, codebase = _indexed(store, tmp_path, WEB)
    selected = _symbol(store, codebase, "UserListComponent#selected", "field")
    preview = preview_rename(store, selected, "chosen")
    places = sorted((p.path.rsplit("/", 1)[-1], p.line) for p in preview.edits if p.selected)
    assert places == [("app.component.ts", 6), ("user-list.component.ts", 10), ("user-list.component.ts", 20)]   # (selected)= binding, declaration, this.selected.emit
    apply_rename(store, selected, "chosen", [p.key for p in preview.edits if p.selected])
    assert "this.chosen.emit(user)" in (root / "angular/src/app/users/user-list.component.ts").read_text()
    assert '(chosen)="onSelected($event)"' in (root / "angular/src/app/app.component.ts").read_text()


def test_a_collision_or_a_reserved_word_is_refused(store, tmp_path):
    _, codebase = _indexed(store, tmp_path, SAMPLE)
    find = _symbol(store, codebase, "com.shop.repo.OrderRepository#find")
    preview = preview_rename(store, find, "save")                   # save(Order) takes one argument too
    assert preview.collision is not None and preview.collision.qualified == "com.shop.repo.OrderRepository#save"
    with pytest.raises(ValueError):
        apply_rename(store, find, "save", [p.key for p in preview.edits])
    with pytest.raises(ValueError):
        preview_rename(store, find, "class")
    assert preview_rename(store, find, "lookup").collision is None


# ---- Blame and history, read-only (ADR-026) ------------------------------------------------------

GAP26 = pytest.mark.xfail(strict=True, reason="ADR-026: not built yet")


def _commit_all(root, message):
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "-A"], cwd=root, check=True)
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message], cwd=root, check=True)
    return subprocess.run([GIT, "rev-parse", "--short", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@needs_git

def test_blame_attributes_lines_and_marks_uncommitted_ones(repo):
    service = repo / "backend/src/main/java/com/shop/service/OrderService.java"
    service.write_text(service.read_text().replace("audit.record(\"place\"", "audit.record(\"placed\""))
    second = _commit_all(repo, "Rename the audit event")
    service.write_text(service.read_text().replace("audit.record(\"placed\"", "audit.record(\"placed!\""))   # Edited, not committed
    lines = git.blame(repo, "backend/src/main/java/com/shop/service/OrderService.java")
    assert len(lines) == len(service.read_text().split("\n")) - 1
    placed = next(l for l in lines if 'audit.record("placed!"' in l.text)
    assert placed.commit == "" and placed.uncommitted
    first = next(l for l in lines if "package com.shop.service" in l.text)
    assert first.commit and first.summary == "start" and first.author == "t" and first.date and not first.uncommitted
    assert git.log(repo)[0].commit == second
    with pytest.raises(ValueError):
        git.blame(repo, "../outside")


@needs_git

def test_a_file_s_history_follows_a_rename_and_a_symbol_s_history_is_only_its_own(repo):
    model = repo / "backend/src/main/java/com/shop/model"
    text = (model / "Order.java").read_text()
    (model / "Order.java").write_text(text.replace("public long getId() { return id; }", "public long getId() {\n        return id;\n    }"))
    touched_get_id = _commit_all(repo, "Reformat getId")
    (model / "Order.java").write_text((model / "Order.java").read_text().replace("return status;", "return status; // read"))
    touched_get_status = _commit_all(repo, "Comment getStatus")
    (model / "Order.java").rename(model / "Purchase.java")
    moved = _commit_all(repo, "Move Order to Purchase")
    history = git.history(repo, "backend/src/main/java/com/shop/model/Purchase.java")
    assert [h.message for h in history] == ["Move Order to Purchase", "Comment getStatus", "Reformat getId", "start"]   # --follow
    lines = (model / "Purchase.java").read_text().split("\n")
    start = next(i for i, l in enumerate(lines, 1) if "getStatus" in l)
    own = git.history(repo, "backend/src/main/java/com/shop/model/Purchase.java", start, start)
    assert [h.commit for h in own] == [touched_get_status, history[-1].commit]   # Not the getId reformat, not the move
    shown = git.show(repo, moved, "backend/src/main/java/com/shop/model/Purchase.java")
    assert shown.message == "Move Order to Purchase" and any(f.path.endswith("Purchase.java") for f in shown.files)
    assert shown.diff.startswith("diff --git") and "Purchase.java" in shown.diff and "OrderService" not in shown.diff   # That path's diff only
    for bad in ("HEAD~1", "main", "abc;rm", "ZZZ"):
        with pytest.raises(ValueError):
            git.show(repo, bad)


def test_git_module_only_reads_and_commits():
    source = (Path(__file__).parent.parent / "src/code/git.py").read_text()
    for forbidden in ("push", "fetch", "pull", "checkout", "reset", "rebase", "merge", "stash", "branch"):
        assert not any(f'"{forbidden}"' in line for line in source.splitlines() if "_run(" in line), forbidden
