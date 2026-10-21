"""Full-text queries on a very large document (ADR-034): the index read first, a search never waiting on the indexer."""
import sqlite3
import time

import pytest

from src.models import Term
from src.search.library import Library


@pytest.fixture
def doc(library, extractor, standard_pdf, model):
    document, _ = library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)
    return document


class _Tracing:
    """A connection wrapper that keeps every statement run against the full-text index."""
    def __init__(self, conn):
        self._conn, self.statements = conn, []

    def execute(self, sql, params=()):
        if "blocks_fts" in sql and "MATCH" in sql:
            self.statements.append((sql, list(params)))
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


def test_every_full_text_query_reads_the_index_first(library, doc, model):
    """Given a document filter the planner would otherwise run the match once per passage of the document."""
    tracing = _Tracing(library.conn)
    library.conn = tracing
    library.search("calibration records", doc_ids=[doc.id], kinds=["text", "heading"], provisions=["requirement"])
    library.search("calibration records", doc_ids=[doc.id], document_order=True)
    library.hit_pages("calibration records", doc.id)
    library.page_matches("calibration records", doc.id, 1)
    block = next(b for b in library.document_blocks(doc.id) if b.kind == "text")
    term = Term(term="calibration", synonyms=(), clause_num="3.1", definition="", doc_id=doc.id, page=1, page_label="1", bbox=None)
    library.related_passages(block, [term])
    library.conn = tracing._conn
    assert len(tracing.statements) >= 6
    for sql, params in tracing.statements:
        plan = [row[3] for row in library.conn.execute("EXPLAIN QUERY PLAN " + sql, params)]
        first = next(step for step in plan if not step.startswith("CO-ROUTINE"))
        assert first.startswith("SCAN blocks_fts"), (sql.strip()[:120], plan)


def test_recording_a_search_never_waits_for_the_indexer(library, doc, tmp_path):
    other = sqlite3.connect(library.conn.execute("PRAGMA database_list").fetchone()[2], check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")   # The indexer's one long transaction while it saves a large document
    other.execute("INSERT INTO meta (key, value) VALUES ('probe', 1)")
    started = time.time()
    library.record_search("while the indexer saves")      # Best-effort: gives up quietly
    assert time.time() - started < 2
    assert library.search("calibration records")[0]      # The search itself is unaffected
    assert library.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15000   # The wait for other writes is kept
    other.rollback()
    library.record_search("after it saved")
    assert "after it saved" in library.recent_searches() and "while the indexer saves" not in library.recent_searches()


def test_a_locked_library_is_explained():
    from src.server.app import _error_message
    assert "indexer" in _error_message(sqlite3.OperationalError("database is locked"))
    assert _error_message(ValueError("Enter at least one word.")) == "Enter at least one word."
