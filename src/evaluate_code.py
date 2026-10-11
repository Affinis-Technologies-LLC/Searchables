"""
Measures how much of a codebase the code index links, per language: the share of calls left by
name is the measure ADR-010 is judged by.

    python -m src.evaluate_code /path/to/codebase
    python -m src.evaluate_code /path/to/codebase --keep library.db   # Keep the index for a look

The folder is indexed into a throwaway library (your own library isn't touched), and for each
language the calls, constructions and type uses are counted by how they were linked: to a symbol of
the codebase, to an outside API by name, or not at all (by name only). The time taken is reported.
"""
import argparse
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict

from src.code.store import CodeStore

KINDS = ("call", "new", "type", "jsx", "use", "annotation", "extends", "implements")


def measure(root: str, db_path: Path, out: Callable[[str], None] = print) -> Dict[str, dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    store = CodeStore(conn)
    codebase = store.add(root)
    started = time.time()
    counts = store.index(codebase.id)
    elapsed = time.time() - started
    out(f"{counts['files']:,} files, {counts['symbols']:,} symbols, indexed in {elapsed:.1f}s "
        f"({counts['files'] / elapsed:.0f} files/s)" if elapsed else "")

    results: Dict[str, dict] = {}
    out(f"\n{'language':12} {'refs':>8} {'linked':>8} {'outside':>8} {'by name':>8}   share by name")
    for kind_group, title in ((("call", "new"), "calls"), (KINDS, "all references")):
        out(f"\n{title}:")
        marks = ", ".join("?" * len(kind_group))
        rows = conn.execute(
            f"""
            SELECT f.language, COUNT(*) AS total,
                   SUM(r.target_id IS NOT NULL) AS linked,
                   SUM(r.target_id IS NULL AND r.target IS NOT NULL) AS outside
            FROM code_refs r JOIN code_files f ON f.id = r.file_id
            WHERE r.codebase_id = ? AND r.kind IN ({marks}) GROUP BY f.language ORDER BY f.language
            """, (codebase.id, *kind_group)).fetchall()
        for row in rows:
            by_name = row["total"] - row["linked"] - row["outside"]
            share = by_name / row["total"] if row["total"] else 0.0
            results.setdefault(row["language"], {})[title] = {"total": row["total"], "linked": row["linked"],
                                                             "outside": row["outside"], "by_name": by_name, "share": share}
            out(f"{row['language']:12} {row['total']:>8,} {row['linked']:>8,} {row['outside']:>8,} {by_name:>8,}   {share:.1%}")
    unresolved = conn.execute(
        "SELECT r.name, COUNT(*) AS n FROM code_refs r WHERE r.codebase_id = ? AND r.kind = 'call' "
        "AND r.target_id IS NULL AND r.target IS NULL GROUP BY r.name ORDER BY n DESC LIMIT 15", (codebase.id,)).fetchall()
    if unresolved:
        out("\nCalls most often left by name: " + ", ".join(f"{r['name']} ({r['n']})" for r in unresolved))
    conn.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure how much of a codebase the code index links.")
    parser.add_argument("root", help="The top folder of the codebase")
    parser.add_argument("--keep", help="Write the index to this file instead of a temporary one")
    args = parser.parse_args()
    if not Path(args.root).is_dir():
        print(f"{args.root} isn't a folder.")
        return 1
    with tempfile.TemporaryDirectory() as temp:
        measure(args.root, Path(args.keep) if args.keep else Path(temp) / "library.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
