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
