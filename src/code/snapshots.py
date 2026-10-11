"""
Index snapshots, diffed (ADR-020): a codebase's symbols kept as they were, and a structural
comparison of two symbol sets (a snapshot against the index now, or two codebases): added, removed,
changed signatures, moved files, and the callers a change affects.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.code.models import Symbol, Usage
from src.code.store import CodeStore


@dataclass
class Snapshot:
    id: int
    codebase_id: int
    label: str
    taken_at: str
    symbol_count: int


@dataclass
class Changed:
    now: Symbol
    before_signature: str
    before_type: str
    callers: List[Usage]


@dataclass
class Moved:
    now: Symbol
    before_path: str


@dataclass
class Diff:
    added: List[Symbol]
    removed: List[Symbol]               # As they were (file and line from before)
    changed: List[Changed]
    moved: List[Moved]
    removed_callers: Dict[str, int]     # Removed symbol → callers it had before
    removed_by_name_now: Dict[str, int] # Removed symbol → references by its name left unlinked now
    by_name_before: int
    by_name_now: int
    against: str


def take_snapshot(store: CodeStore, codebase_id: int, label: str = "") -> Snapshot:
    conn = store.conn
    taken_at = datetime.now().isoformat(timespec="seconds")
    by_name = conn.execute("SELECT COUNT(*) FROM code_refs WHERE codebase_id = ? AND kind = 'call' AND target_id IS NULL AND target IS NULL",
                           (codebase_id,)).fetchone()[0]
    with conn:
        snapshot_id = conn.execute("INSERT INTO code_snapshots (codebase_id, label, taken_at, symbol_count, by_name) VALUES (?, ?, ?, 0, ?)",
                                   (codebase_id, label or taken_at, taken_at, by_name)).lastrowid
        conn.execute(
            "INSERT INTO code_snapshot_symbols (snapshot_id, kind, qualified, params, name, signature, type, path, line, exported, callers) "
            "SELECT ?, s.kind, s.qualified, s.params, s.name, s.signature, s.type, f.path, s.line, s.exported, "
            "(SELECT COUNT(*) FROM code_refs r WHERE r.target_id = s.id AND r.kind IN ('call', 'new', 'jsx')) "
            "FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE s.codebase_id = ?", (snapshot_id, codebase_id))
        count = conn.execute("SELECT COUNT(*) FROM code_snapshot_symbols WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
        conn.execute("UPDATE code_snapshots SET symbol_count = ? WHERE id = ?", (count, snapshot_id))
    return Snapshot(snapshot_id, codebase_id, label or taken_at, taken_at, count)


def _identity(row) -> Tuple[str, str, int]:
    return row["kind"], row["qualified"], row["params"]


def _symbol_from_before(row, codebase_id: int) -> Symbol:
    return Symbol(id=0, codebase_id=codebase_id, file_id=0, parent_id=None, kind=row["kind"], name=row["name"], qualified=row["qualified"],
                  line=row["line"], end_line=row["line"], signature=row["signature"], params=row["params"], exported=bool(row["exported"]),
                  path=row["path"], language="", type=row["type"])


def diff_against(store: CodeStore, codebase_id: int, snapshot_id: Optional[int] = None, codebase_id_before: Optional[int] = None) -> Diff:
    """The codebase now against a snapshot of it, or against another codebase (the baseline)."""
    conn = store.conn
    baseline = codebase_id_before
    if snapshot_id is not None:
        before = conn.execute("SELECT * FROM code_snapshot_symbols WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
        by_name_before = conn.execute("SELECT by_name FROM code_snapshots WHERE id = ?", (snapshot_id,)).fetchone()[0]
        against = f"snapshot:{snapshot_id}"
    elif baseline is not None:
        before = conn.execute(
            "SELECT s.kind, s.qualified, s.params, s.name, s.signature, s.type, f.path, s.line, s.exported, "
            "(SELECT COUNT(*) FROM code_refs r WHERE r.target_id = s.id AND r.kind IN ('call', 'new', 'jsx')) AS callers "
            "FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE s.codebase_id = ?", (baseline,)).fetchall()
        by_name_before = conn.execute("SELECT COUNT(*) FROM code_refs WHERE codebase_id = ? AND kind = 'call' AND target_id IS NULL AND target IS NULL",
                                      (baseline,)).fetchone()[0]
        against = f"codebase:{baseline}"
    else:
        raise ValueError("Say what to compare against: a snapshot or another codebase.")
    now = conn.execute("SELECT s.*, f.path FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE s.codebase_id = ?", (codebase_id,)).fetchall()
    before_by = {_identity(r): r for r in before}
    now_by = {_identity(r): r for r in now}
    added = [store.symbol(r["id"]) for key, r in sorted(now_by.items()) if key not in before_by]
    removed = [_symbol_from_before(r, codebase_id) for key, r in sorted(before_by.items()) if key not in now_by]
    changed, moved = [], []
    for key, r in sorted(now_by.items()):
        b = before_by.get(key)
        if b is None:
            continue
        symbol = None
        if b["signature"] != r["signature"] or b["type"] != r["type"]:
            symbol = store.symbol(r["id"])
            changed.append(Changed(symbol, b["signature"], b["type"], store.callers(symbol)))
        if b["path"] != r["path"]:
            moved.append(Moved(symbol or store.symbol(r["id"]), b["path"]))
    removed_callers = {s.qualified: before_by[(s.kind, s.qualified, s.params)]["callers"] for s in removed}
    removed_by_name_now = {}
    for s in removed:
        removed_by_name_now[s.qualified] = conn.execute(
            "SELECT COUNT(*) FROM code_refs WHERE codebase_id = ? AND name = ? AND target_id IS NULL AND target IS NULL", (codebase_id, s.name)).fetchone()[0]
    by_name_now = conn.execute("SELECT COUNT(*) FROM code_refs WHERE codebase_id = ? AND kind = 'call' AND target_id IS NULL AND target IS NULL",
                               (codebase_id,)).fetchone()[0]
    return Diff(added, removed, changed, moved, removed_callers, removed_by_name_now, by_name_before, by_name_now, against)
