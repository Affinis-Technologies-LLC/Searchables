"""
Examples for what's being written (ADR-012): call sites of the codebase that pass a hard filter
(same member on the same type first, then siblings, then the same name anywhere, then code written
in a method like this one), ranked by a deterministic, explained score. Nothing is generated: every
example is a statement that exists, with its file and lines.
"""
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from src import config
from src.code.context import Context
from src.code.parser import JAVA, TYPE_KINDS
from src.code.store import CodeStore

SAME_MEMBER = "same member on the same type"
SAME_FUNCTION = "same function"
SIBLINGS = "same member on sibling types"
SAME_API = "same outside API"
SAME_NAME = "same name on any type"
LIKE_THIS = "methods like this one"
FEW = 3   # With fewer own examples than this, siblings are added


@dataclass
class Example:
    ref_id: int
    file_id: int
    path: str
    line: int
    col: int
    start: int                  # The statement's lines
    end: int
    lines: List[str]            # The statement with a little around it
    first_line: int             # Line number of lines[0]
    statement: str
    enclosing: str              # Qualified name of the method it's in
    enclosing_id: Optional[int]
    target: str                 # What the call was linked to (qualified, or an outside API)
    certainty: str              # resolved, or "by name"
    features: Dict[str, float]
    score: float
    reason: str


@dataclass
class Examples:
    filter: str
    by_name: bool
    examples: List[Example]
    unranked: List[Example] = field(default_factory=list)   # The same, in path order (the measure's baseline)


def score(features: Dict[str, float]) -> float:
    return round(sum(config.EXAMPLE_WEIGHTS[key] * features.get(key, 0.0) for key in config.EXAMPLE_WEIGHTS), 4)


# ---- Candidates ------------------------------------------------------------------------------------

@dataclass
class _Candidate:
    row: sqlite3.Row
    T: float
    M: float
    reason: str
    certainty: str = "resolved"


def _refs(conn: sqlite3.Connection, where: str, params: Sequence) -> List[sqlite3.Row]:
    return conn.execute(
        f"SELECT r.*, f.path, s.qualified AS enclosing, t.qualified AS target_name "
        f"FROM code_refs r JOIN code_files f ON f.id = r.file_id "
        f"LEFT JOIN code_symbols s ON s.id = r.from_symbol LEFT JOIN code_symbols t ON t.id = r.target_id "
        f"WHERE r.kind IN ('call', 'new') AND r.chain != '=' AND {where} ORDER BY f.path, r.line LIMIT ?",
        [*params, config.EXAMPLE_CANDIDATES]).fetchall()


def _members(linker, type_id: int, name: str, partial: str, seen: Optional[Set[int]] = None, depth: int = 0) -> List[Tuple[int, int]]:
    """(member id, depth) for members of a type and its supertypes matching the name or prefix."""
    seen = seen if seen is not None else set()
    if type_id in seen:
        return []
    seen.add(type_id)
    found = []
    for member_name, members in linker.members.get(type_id, {}).items():
        if (name and member_name == name) or (not name and member_name.lower().startswith(partial.lower())):
            found += [(m["id"], depth) for m in members if m["kind"] in ("method", "function", "field", "constructor")]
    for parent in linker.supers.get(type_id, []):
        found += _members(linker, parent, name, partial, seen, depth + 1)
    return found


def _siblings(linker, type_id: int) -> List[int]:
    parents = set(linker.supers.get(type_id, []))
    return [t for t, supers in linker.supers.items() if t != type_id and parents & set(supers)]


def _short(qualified: str) -> str:
    return qualified.rsplit(".", 1)[-1]


def _owner(target_name: str) -> str:
    return _short(target_name.split("#")[0])


def candidates(store: CodeStore, context: Context) -> Tuple[str, List[_Candidate]]:
    conn, linker = store.conn, store.linker(context.codebase_id)
    expression, type_ref = context.expression, context.receiver_type
    name, partial = expression.name, expression.partial
    found: List[_Candidate] = []
    arity = expression.args_so_far

    def overload(member_id: int) -> bool:
        params = linker.symbols[member_id]["params"]
        return arity >= 0 and params >= 0 and params != arity and name != ""

    if expression.kind in ("call", "new") and type_ref is not None and type_ref.id is not None:
        members = _members(linker, type_ref.id, name, partial)
        if expression.kind == "new":
            members = [(m, d) for m, d in members if linker.symbols[m]["kind"] == "constructor"]
        for member_id, depth in members:
            member = linker.symbols[member_id]
            owner = _short(linker.symbols[member["parent_id"]]["qualified"]) if member["parent_id"] else ""
            for row in _refs(conn, "r.target_id = ?", [member_id]):
                found.append(_Candidate(row, 1.0 if depth == 0 else 0.8, 0.5 if overload(member_id) else 1.0,
                                        f"Same `{owner}.{member['name']}`" + (" (inherited)" if depth else "")))
        own = len({c.row["from_symbol"] for c in found})
        if own < FEW and name or (not found and partial):
            for sibling in _siblings(linker, type_ref.id):
                for member_id, depth in _members(linker, sibling, name, partial):
                    if depth:
                        continue
                    member = linker.symbols[member_id]
                    for row in _refs(conn, "r.target_id = ?", [member_id]):
                        found.append(_Candidate(row, 0.5, 0.35 if overload(member_id) else 0.7,
                                                f"`{member['name']}` on `{_short(sibling_name(linker, sibling))}`, a sibling of `{_short(type_ref.qualified)}`"))
        if found:
            return (SAME_MEMBER if any(c.T >= 0.8 for c in found) else SIBLINGS), found

    if expression.kind == "call" and type_ref is not None and type_ref.id is None and name:
        owner = type_ref.qualified
        target = f"{owner}{'.' if '#' in owner else '#'}{name}"
        for row in _refs(conn, "r.codebase_id = ? AND r.target = ?", [context.codebase_id, target]):
            found.append(_Candidate(row, 1.0, 1.0, f"Same outside API `{target.replace('#', '.').lstrip('.')}`"))
        if found:
            return SAME_API, found

    if expression.kind == "call" and not expression.receiver and name:
        # A bare call: what the linker would link it to
        target = linker._link({"file_id": context.file_id, "from_symbol": context.enclosing.id if context.enclosing else None,
                               "kind": "call", "name": name, "receiver": "", "args": arity, "chain": ""})
        if isinstance(target, int):
            for row in _refs(conn, "r.target_id = ?", [target]):
                found.append(_Candidate(row, 1.0, 1.0, f"Same `{linker.symbols[target]['qualified']}`"))
            if found:
                return SAME_FUNCTION, found
        elif isinstance(target, str):
            for row in _refs(conn, "r.codebase_id = ? AND r.target = ?", [context.codebase_id, target]):
                found.append(_Candidate(row, 1.0, 1.0, f"Same outside API `{target.replace('#', '.').lstrip('.')}`"))
            if found:
                return SAME_API, found

    if expression.kind in ("call", "new") and (name or partial):
        kind = expression.kind
        where = "r.codebase_id = ? AND r.kind = ? AND (r.target_id IS NOT NULL OR r.target IS NOT NULL) AND "
        params: list = [context.codebase_id, kind]
        if name:
            where += "r.name = ?"
            params.append(name)
        else:
            where += "r.name LIKE ? ESCAPE '\\'"
            params.append(partial.replace("%", "\\%").replace("_", "\\_") + "%")
        for row in _refs(conn, where, params):
            what = row["target_name"] or row["target"] or row["name"]
            owner = _owner(what) if "#" in what else ""
            found.append(_Candidate(row, 0.3, 0.2, (f"Same name `{row['name']}` on `{owner}`" if owner else f"Same name `{row['name']}`")
                                    + " — not linked for certain", "by name"))
        if found:
            return SAME_NAME, found

    # Nothing resolves: code written in methods most like this one
    names = sorted(context.neighbours.names())
    if names:
        marks = ", ".join("?" * len(names))
        rows = conn.execute(   # Bounded: on a codebase where every method calls the same names, the scan would be the whole index
            f"SELECT from_symbol, COUNT(DISTINCT name) AS shared FROM (SELECT from_symbol, name FROM code_refs INDEXED BY code_refs_name "
            f"WHERE codebase_id = ? AND from_symbol IS NOT NULL AND name IN ({marks}) LIMIT 20000) "
            f"GROUP BY from_symbol ORDER BY shared DESC, from_symbol LIMIT 20", [context.codebase_id, *names]).fetchall()
        for row in rows:
            refs = _refs(conn, "r.from_symbol = ?", [row["from_symbol"]])
            if not refs:
                continue
            pick = next((r for r in refs if r["name"] == name), None) or next((r for r in refs if r["name"] in names), refs[0])
            shared = sorted({r["name"] for r in refs} & set(names))[:3]
            found.append(_Candidate(pick, 0.0, 0.0, "Written in a method like this one" + (f" (shares {', '.join(shared)})" if shared else ""), "by name"))
        if found:
            return LIKE_THIS, found
    return LIKE_THIS, []


def sibling_name(linker, type_id: int) -> str:
    return linker.symbols[type_id]["qualified"]


# ---- Ranking --------------------------------------------------------------------------------------

def _lcs(a: str, b: str) -> int:
    if not a or not b:
        return 0
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            table[i][j] = table[i - 1][j - 1] + 1 if x == y else max(table[i - 1][j], table[i][j - 1])
    return table[-1][-1]


def structural(shape: str, other: str) -> float:
    a, b = shape.lower(), other.lower()
    return _lcs(a, b) / max(len(a), len(b)) if a and b else 0.0


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def quality(row: sqlite3.Row, statement: str) -> float:
    lines = (row["stmt_end"] - row["stmt_start"] + 1) if row["stmt_end"] else 1
    q = 1.0 if lines <= 3 else 0.7 if lines <= 6 else 0.4
    if row["target_id"] is None and row["target"] is None:
        q -= 0.3
    dense = "".join(statement.split())
    if dense and sum(dense.count(c) for c in "\"'`") + sum(len(s) for s in _strings(statement)) > 0.4 * len(dense):
        q -= 0.2
    return max(0.0, min(1.0, round(q, 2)))


def _strings(text: str) -> List[str]:
    out, quote, start = [], "", 0
    for i, c in enumerate(text):
        if quote:
            if c == quote and text[i - 1] != "\\":
                out.append(text[start:i])
                quote = ""
        elif c in "\"'`":
            quote, start = c, i + 1
    return out


def _neighbour_names(conn: sqlite3.Connection, symbol_id: Optional[int], cache: Dict[int, Set[str]]) -> Set[str]:
    if symbol_id is None:
        return set()
    if symbol_id not in cache:
        cache[symbol_id] = {row[0] for row in conn.execute(
            "SELECT name FROM code_refs WHERE from_symbol = ? AND kind IN ('call', 'new', 'type')", (symbol_id,))}
    return cache[symbol_id]


def examples_for(store: CodeStore, context: Context, limit: int = config.EXAMPLES_SHOWN) -> Examples:
    filter_name, found = candidates(store, context)
    conn = store.conn
    current = context.enclosing.id if context.enclosing else None
    mine = context.neighbours.names()
    cache: Dict[int, Set[str]] = {}
    best: Dict[Tuple[Optional[int], int], Example] = {}   # One example per enclosing method (or per file when unknown)
    for candidate in found:
        row = candidate.row
        if current is not None and row["from_symbol"] == current:
            continue   # Never the method being written
        if row["file_id"] == context.file_id and context.enclosing and context.enclosing.line <= row["line"] <= context.enclosing.end_line:
            continue
        start, end = (row["stmt_start"], row["stmt_end"]) if row["stmt_end"] else (row["line"], row["line"])
        text = store.lines(row["file_id"])
        statement = "\n".join(text[start - 1:end])
        features = {
            "T": candidate.T, "M": candidate.M,
            "C": round(jaccard(mine, _neighbour_names(conn, row["from_symbol"], cache)), 3),
            "P": round(structural(context.neighbours.shape, row["shape"]), 3),
            "Q": quality(row, statement),
        }
        first = max(1, start - 2)
        last = min(len(text), end + 2)
        target = row["target_name"] or row["target"] or ""
        enclosing = row["enclosing"] or ""
        reason = candidate.reason + (f", called from `{_short(enclosing)}`" if enclosing and candidate.T else "")
        example = Example(row["id"], row["file_id"], row["path"], row["line"], row["col"], start, end,
                          text[first - 1:last], first, statement, enclosing, row["from_symbol"], target,
                          candidate.certainty, features, score(features), reason)
        key = (row["from_symbol"], 0 if row["from_symbol"] is not None else row["file_id"])
        if key not in best or example.score > best[key].score:
            best[key] = example
    ranked = sorted(best.values(), key=lambda e: (-e.score, e.path, e.line))[:limit]
    unranked = sorted(best.values(), key=lambda e: (e.path, e.line))[:limit]
    return Examples(filter_name, filter_name in (SAME_NAME, LIKE_THIS), ranked, unranked)
