"""
Measures search quality against your own library, so thresholds in config.py are tuned on evidence.

    python -m src.evaluate                      # Uses <data dir>/eval_queries.json
    python -m src.evaluate my_queries.json --k 10

The queries file lists searches and the passages a good search must find (see
eval_queries.example.json). An expected passage is described by any of: "document" (part of its
title), "clause" (its clause number), "page" (printed or physical) and "text" (words it contains);
a result counts when it matches every field given. Keep the file in the data folder, not the
repository: it describes your documents.

Each query is run three ways (words only, meaning only, and combined as the app does) and reported
with the rank of the first expected passage. For passages that meaning search missed, the report
shows how similar the model found them, which is what MEANING_MIN_SIMILARITY and MEANING_BAND cut on.
"""
import argparse
import json
import sys
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from src import config
from src.models import TextBlock
from src.search import semantic
from src.search.library import Library, _row_to_block, _similarities, uses_meaning

MODES = ("words", "meaning", "combined")


def matches(block: TextBlock, doc_title: str, expected: dict) -> bool:
    """Whether a passage is the one an expectation describes (every field given must agree)."""
    if "document" in expected and expected["document"].lower() not in doc_title.lower():
        return False
    if "clause" in expected and block.clause_num != str(expected["clause"]):
        return False
    if "page" in expected and str(expected["page"]) not in (str(block.page), block.page_label):
        return False
    if "text" in expected and " ".join(expected["text"].lower().split()) not in block.text.lower():
        return False
    return True


def first_hit(blocks: Sequence[TextBlock], titles: Dict[int, str], expect: Sequence[dict]) -> Optional[int]:
    """Rank (from 1) of the first passage matching any expectation."""
    for rank, block in enumerate(blocks, 1):
        if any(matches(block, titles.get(block.doc_id, ""), e) for e in expect):
            return rank
    return None


def _expected_similarity(library: Library, query: str, titles: Dict[int, str], expect: Sequence[dict]) -> Optional[float]:
    """The best meaning similarity between the query and any expected passage (None without vectors)."""
    vectors = library._vectors()
    if vectors is None or not semantic.model_files_present():
        return None
    expected = [row["id"] for row in library.conn.execute("SELECT * FROM blocks")
                if any(matches(_row_to_block(row), titles.get(row["doc_id"], ""), e) for e in expect)]
    wanted = np.flatnonzero(np.isin(vectors.ids, expected))
    if not len(wanted):
        return None
    return float(_similarities(vectors.matrix, semantic.embed_query(query), wanted).max())


def evaluate(library: Library, queries: Sequence[dict], k: int = 10, out: Callable[[str], None] = print) -> Dict[str, dict]:
    """Runs every query in each mode; returns per-mode {"found": share in the top k, "mrr": mean reciprocal rank}."""
    titles = {d.id: d.title for d in library.list_documents()}
    ranks: Dict[str, List[Optional[int]]] = {mode: [] for mode in MODES}
    out(f"{'words':>6} {'meaning':>8} {'combined':>9}   query")
    for entry in queries:
        query, expect = entry["query"], entry["expect"]
        found = {
            "words": [r.block for r in library.search(query, limit=k, use_meaning=False)[0]],
            "meaning": [library.get_block(block_id) for block_id, _, _ in library._meaning_matches(query)[:k]]
                       if uses_meaning(query) else [],
            "combined": [r.block for r in library.search(query, limit=k)[0]],
        }
        row = {mode: first_hit(found[mode], titles, expect) for mode in MODES}
        for mode in MODES:
            ranks[mode].append(row[mode])
        note = ""
        if row["meaning"] is None and uses_meaning(query):
            similarity = _expected_similarity(library, query, titles, expect)
            note = "   (no expected passage has a vector)" if similarity is None else f"   (expected passage's similarity: {similarity:.3f})"
        out(f"{row['words'] or '-':>6} {row['meaning'] or '-':>8} {row['combined'] or '-':>9}   {query}{note}")

    summary = {
        mode: {
            "found": sum(r is not None for r in ranks[mode]) / len(queries),
            "mrr": sum(1 / r for r in ranks[mode] if r) / len(queries),
        }
        for mode in MODES
    }
    out("")
    for mode in MODES:
        out(f"{mode:>9}: found in the top {k} for {summary[mode]['found']:.0%} of queries · "
            f"mean reciprocal rank {summary[mode]['mrr']:.3f}")
    out(f"\nThresholds in use: MEANING_MIN_SIMILARITY {config.MEANING_MIN_SIMILARITY}, MEANING_BAND {config.MEANING_BAND}, "
        f"PARTIAL_MATCH_BELOW {config.PARTIAL_MATCH_BELOW}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure search quality against expected passages.")
    parser.add_argument("queries", nargs="?", default=str(config.DATA_DIR / "eval_queries.json"))
    parser.add_argument("--k", type=int, default=10, help="A query counts as found when an expected passage is in the top k")
    args = parser.parse_args()
    try:
        with open(args.queries, encoding="utf-8") as f:
            queries = json.load(f)
    except OSError:
        print(f"No queries file at {args.queries}. Copy eval_queries.example.json there and describe your own searches.")
        return 1
    if not queries:
        print("The queries file is empty.")
        return 1
    evaluate(Library(), queries, args.k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
