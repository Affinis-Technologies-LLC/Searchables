"""
Measures the examples shown as you type (ADR-012) against a judged set, and against two baselines:
plain text search for the name being written, and the same candidates in path order without ranking.

    python -m src.evaluate_examples tests/examples_set.json
    python -m src.evaluate_examples my_set.json --show      # Prints what each context got, for judging

The set is a JSON file: {"codebase": "<folder, relative to the set file or absolute>", "contexts": [
  {"file": "<path in the codebase>", "after": "<a line of the file; the typing goes after it>",
   "typed": "<what the developer has typed>", "useful": ["File.java#method", …], "why": "<the judge's reason>"}]}.
Precision@3 is the share of the top three the judge marked useful; MRR the reciprocal rank of the first
useful one. Reported per language.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List

from src.code.context import context_at
from src.code.examples import examples_for
from src.code.store import CodeStore


def _where(path: str, enclosing: str) -> str:
    return f"{path.rsplit('/', 1)[-1]}#{enclosing.split('#')[-1].rsplit('.', 1)[-1] if enclosing else '?'}"


def _text_search(store: CodeStore, codebase_id: int, name: str, exclude: str) -> List[str]:
    """The methods whose lines contain the name, in the order text search lists them."""
    seen: List[str] = []
    outlines: Dict[int, list] = {}
    for file, line, _ in store.search_text(codebase_id, name, limit=500):
        if file.id not in outlines:
            outlines[file.id] = store.outline(file.id)
        enclosing = next((s for s in sorted(outlines[file.id], key=lambda s: -s.line) if s.line <= line <= s.end_line
                          and s.kind in ("method", "function", "constructor")), None)
        where = _where(file.path, enclosing.qualified if enclosing else "")
        if where != exclude and where not in seen:
            seen.append(where)
    return seen


def _precision_at_3(ranked: List[str], useful: set) -> float:
    return len([w for w in ranked[:3] if w in useful]) / 3


def _mrr(ranked: List[str], useful: set) -> float:
    return next((1 / (i + 1) for i, w in enumerate(ranked) if w in useful), 0.0)


def evaluate(set_path: Path, db_path: Path, out: Callable[[str], None] = lambda _: None, show: bool = False) -> Dict[str, dict]:
    spec = json.loads(Path(set_path).read_text())
    root = Path(spec["codebase"])
    if not root.is_absolute():
        root = (Path(set_path).parent / root).resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(root))
    store.index(codebase.id)
    totals: Dict[str, Dict[str, list]] = {}
    for item in spec["contexts"]:
        file = next(f for f in store.files(codebase.id) if f.path == item["file"])
        text = store.text(file.id)
        position = text.index(item["after"]) + len(item["after"])
        if not text[position:].startswith("\n"):
            position = text.index("\n", position)
        buffer = text[:position + 1] + item["typed"] + text[position:]
        at = position + 1 + len(item["typed"])
        line = buffer.count("\n", 0, at) + 1
        col = at - (buffer.rfind("\n", 0, at) + 1) + 1
        context = context_at(store, file.id, buffer, line, col)
        result = examples_for(store, context)
        mine = _where(file.path, context.enclosing.qualified if context.enclosing else "")
        ranked = [_where(e.path, e.enclosing) for e in result.examples]
        unranked = [_where(e.path, e.enclosing) for e in result.unranked]
        name = context.expression.name or context.expression.partial
        text_hits = _text_search(store, codebase.id, name, mine) if name else []
        useful = set(item["useful"])
        language = file.language
        for system, order in (("ranked", ranked), ("unranked", unranked), ("text search", text_hits)):
            bucket = totals.setdefault(language, {}).setdefault(system, [])
            bucket.append((_precision_at_3(order, useful), _mrr(order, useful)))
        if show:
            out(f"\n{item['file']} · {item['typed']!r} → {result.filter}")
            out(f"  ranked:  {ranked[:5]}")
            out(f"  path:    {unranked[:5]}")
            out(f"  text:    {text_hits[:5]}")
            out(f"  useful:  {sorted(useful)}  ({item.get('why', '')})")
    report: Dict[str, dict] = {}
    out(f"\n{'language':12} {'system':12} {'contexts':>8} {'precision@3':>12} {'mrr':>8}")
    for language, systems in totals.items():
        report[language] = {"contexts": len(systems["ranked"])}
        for system, pairs in systems.items():
            p3 = sum(p for p, _ in pairs) / len(pairs)
            mrr = sum(m for _, m in pairs) / len(pairs)
            report[language][system] = {"precision@3": round(p3, 3), "mrr": round(mrr, 3)}
            out(f"{language:12} {system:12} {len(pairs):>8} {p3:>12.3f} {mrr:>8.3f}")
    conn.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure examples-as-you-type against a judged set.")
    parser.add_argument("set", help="The judged set (JSON)")
    parser.add_argument("--show", action="store_true", help="Print what each context got")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        evaluate(Path(args.set), Path(temp) / "eval.db", print, args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
