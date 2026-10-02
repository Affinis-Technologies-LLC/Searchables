"""Extraction, search, meaning vectors and background indexing, on a made-up standard."""
import os
import sqlite3
import stat
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import fake_vectors, make_pdf
from src import config
from src.evaluate import evaluate
from src.search import semantic
from src.code.store import CodeStore
from src.search.indexer import ADD, CODE, DONE, EMBED, FAILED, Indexer
from src.search.library import Library


@pytest.fixture
def doc(library, extractor, standard_pdf, model):
    document, _ = library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)
    return document


def by_text(library, doc, start):
    return next(b for b in library.document_blocks(doc.id) if b.text.startswith(start))


# ---- Extraction --------------------------------------------------------------------------------

def test_extraction_reads_structure(library, doc):
    blocks = library.document_blocks(doc.id)
    assert not any("ACME-STD-1234 Rev B" in b.text or b.text.startswith("Page ") for b in blocks)  # Running text
    assert by_text(library, doc, "Message K3.5 shall").clause_num == "4.2.1.1.1.1.1"
    assert by_text(library, doc, "20.1 Interval").clause_path == "Appendix A › 20 SCHEDULE › 20.1 Interval"
    assert by_text(library, doc, "a. Transmit").provision == "requirement"       # From "The terminal shall … :"
    assert by_text(library, doc, "b. Cease").provision == "requirement"
    assert by_text(library, doc, "The operator should").provision == "recommendation"
    assert by_text(library, doc, "NOTE").provision == "note"

    table = by_text(library, doc, "TABLE 1")
    assert (table.kind, table.label) == ("table", "Table 1")
    parts = library.table_parts(table)
    assert parts[0][1].columns == ["Message", "Field", "Purpose"] and len(parts[0][1].rows) == 3


def test_identifier_search_groups_table_rows(library, doc):
    hits = library.identifier_search("k 3.5")
    assert [h.group for h in hits] == ["table", "rule"]
    assert hits[0].rows == (1,)
    library.set_family_enabled(doc.id, "FLD#", True)   # Too few passages here to be switched on by discovery
    related = library.related_identifiers("K3.5")
    assert related.related[0].value == "FLD 2041" and related.related[0].same_row == 1


# ---- Search ------------------------------------------------------------------------------------

def test_search_by_words_and_exact_syntax(library, doc):
    results, total = library.search("calibration records", use_meaning=False)
    assert [r.match for r in results].count("keyword") == 1 and total == len(results)
    assert results[0].match == "keyword" and "<mark" in results[0].highlighted_text
    assert library.search('"shall be retained"')[1] == 1
    assert library.search('"shall be retained" -calibration')[0] == []
    with pytest.raises(ValueError):
        library.search("...")


def test_a_question_finds_passages_with_some_of_its_words(library, doc):
    """No passage has every word of the question; before, the keyword search then found nothing."""
    results, total = library.search("how long must calibration records be kept", use_meaning=False)
    assert results[0].block.text.startswith("Calibration records shall be retained")
    assert results[0].match == "some" and total == len(results)
    # Exact syntax still means exactly those words
    assert library.search('"calibration records" kept', use_meaning=False)[0] == []


def test_many_exact_matches_are_not_padded_with_partial_ones(library, doc, monkeypatch):
    monkeypatch.setattr(config, "PARTIAL_MATCH_BELOW", 1)
    results, _ = library.search("item report", use_meaning=False)
    assert results and all(r.match == "keyword" for r in results)


def test_search_merges_meaning_matches(library, doc, monkeypatch):
    monkeypatch.setattr(config, "MEANING_MIN_SIMILARITY", 0.3)
    results, _ = library.search("lubricant replaced every 6 months")
    assert results[0].block.text.startswith("20.1 Interval") and results[0].match == "both"
    # Filters apply to meaning matches too
    assert all(r.block.provision == "note" for r in library.search("lubricant replaced", provisions=["note"])[0])


def test_long_tables_are_found_by_their_rows(library, extractor, model, monkeypatch):
    monkeypatch.setattr(config, "EMBEDDING_TABLE_CHARS", 150)
    monkeypatch.setattr(config, "MEANING_MIN_SIMILARITY", 0.15)
    rows = [["Message", "Purpose"]] + [[f"K{i}.1", f"filler entry number {i}"] for i in range(1, 12)]
    rows[9] = ["K9.1", "hydraulic accumulator precharge"]
    pdf = make_pdf([["1 SCOPE", "1.1 Purpose. This standard lists the messages of the interface.",
                     {"caption": "TABLE 1. Messages", "rows": rows}]])
    doc, _ = library.add_document(pdf, "tables.pdf", extractor)
    chunks = library.conn.execute("SELECT first_row, last_row FROM table_embeddings ORDER BY first_row").fetchall()
    assert len(chunks) > 1 and chunks[0][0] == 1 and chunks[-1][1] == 11

    monkeypatch.setattr(config, "PARTIAL_MATCH_BELOW", 0)  # Meaning alone
    results, _ = library.search("accumulator precharge pressure")
    assert results[0].block.kind == "table" and results[0].match == "meaning"
    assert 9 in results[0].rows and 1 not in results[0].rows


# ---- Meaning vectors ---------------------------------------------------------------------------

def test_vectors_are_stored_at_half_precision_and_old_ones_still_load(library, doc):
    blob = library.conn.execute("SELECT vector FROM embeddings LIMIT 1").fetchone()[0]
    assert len(blob) == config.EMBEDDING_DIMENSIONS * 2
    vectors = library._vectors()
    with library.conn:  # A library made before: float32
        library.conn.execute("UPDATE embeddings SET vector = ? WHERE block_id = ?",
                             (vectors.matrix[0].astype(np.float32).tobytes(), int(vectors.ids[0])))
        library._touch_vectors()
    assert np.array_equal(library._vectors().matrix[0], vectors.matrix[0])


def test_vectors_reload_when_another_connection_re_embeds(library, doc, tmp_path, monkeypatch):
    before = library._vectors().matrix.copy()
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: fake_vectors(["x " + t for t in texts]))
    monkeypatch.setattr(config, "EMBEDDING_ID", "another-model")
    Library(tmp_path / "library.db", tmp_path / "pdfs").embed_document(doc.id)   # As the indexer's thread does
    after = library._vectors().matrix
    assert after.shape == before.shape and not np.array_equal(after, before)


def test_vectors_from_another_model_are_not_searched(library, doc, monkeypatch):
    assert library._vectors() is not None
    monkeypatch.setattr(config, "EMBEDDING_ID", "another-model")
    with library.conn:
        library._touch_vectors()
    assert library._vectors() is None
    assert [d.id for d in library.documents_without_meaning()] == [doc.id]


def test_embedding_resumes_where_it_stopped(library, extractor, standard_pdf, model, monkeypatch):
    monkeypatch.setattr(config, "EMBEDDING_COMMIT", 4)
    calls = []

    def failing(texts, on_progress=None):
        calls.append(list(texts))
        if len(calls) == 3:
            raise RuntimeError("stopped")
        return fake_vectors(texts)

    monkeypatch.setattr(semantic, "embed_passages", failing)
    doc, _ = library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)   # Fails part-way; kept searchable
    assert doc.embedding_model == "" and doc.embedding_started == config.EMBEDDING_ID
    assert library.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 8
    assert library.search("calibration records")[0][0].match == "keyword" and library._vectors() is None

    calls.clear()
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: calls.append(list(texts)) or fake_vectors(texts))
    total = library.embed_document(doc.id)
    assert sum(map(len, calls)) == total - 8                                       # Only what was missing
    assert library.get_document(doc.id).embedding_model == config.EMBEDDING_ID
    assert len(library._vectors().ids) == total


def test_same_topic_passages_are_assessed(library, extractor, model, monkeypatch):
    monkeypatch.setattr(config, "SAME_TOPIC_MIN_SIMILARITY", 0.6)
    monkeypatch.setattr(config, "SAME_TOPIC_SENTENCE_SIMILARITY", 0.6)
    pages = lambda months: [["1 SCOPE", "1.1 Records",
                             f"Calibration records for the test equipment shall be retained for a period of {months} months."]]
    old, _ = library.add_document(make_pdf(pages(12)), "old.pdf", extractor)
    library.add_document(make_pdf(pages(6)), "new.pdf", extractor)
    related = library.related_passages(by_text(library, old, "Calibration records"))
    finding = related["same_topic"][0].findings[0]
    assert (finding.label, finding.detail) == ("Different value", "12 months → 6 months")


# ---- Library housekeeping ----------------------------------------------------------------------

def test_duplicate_reindex_and_delete(library, extractor, standard_pdf, doc):
    again, extracted = library.add_document(standard_pdf, "copy.pdf", extractor)
    assert again.id == doc.id and extracted is None
    library.reindex_document(doc.id, extractor)
    assert library.get_document(doc.id).embedding_model == config.EMBEDDING_ID
    library.delete_document(doc.id)
    assert library.list_documents() == [] and library._vectors() is None
    assert not library.pdf_path(doc.sha256).exists()
    assert library.conn.execute("SELECT COUNT(*) FROM table_embeddings").fetchone()[0] == 0


def test_an_unusable_pdf_leaves_nothing_behind(library, extractor):
    with pytest.raises(ValueError):
        library.add_document(b"not a pdf", "broken.pdf", extractor)
    assert list(library.pdf_dir.iterdir()) == [] and library.list_documents() == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses the folder's ACL, set by the install script")
def test_library_folders_are_private(library, tmp_path):
    for folder in (tmp_path, tmp_path / "pdfs"):
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700


def test_a_library_from_before_these_changes_is_migrated(tmp_path):
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.executescript("""
        CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE, page_count INTEGER NOT NULL, block_count INTEGER NOT NULL,
            ocr_pages INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL, extract_version INTEGER NOT NULL DEFAULT 1);
        INSERT INTO documents VALUES (1, 'Old', 'old.pdf', 'abc', 1, 0, 0, '2026-01-01', 3);
    """)
    conn.close()
    library = Library(tmp_path / "library.db", tmp_path / "pdfs")
    old = library.list_documents()[0]
    assert (old.embedding_model, old.embedding_started) == ("", "") and library.outdated_documents() == [old]


# ---- Background indexing -----------------------------------------------------------------------

def wait(indexer, timeout=30):
    deadline = time.time() + timeout
    while indexer.active():
        assert time.time() < deadline, "indexing didn't finish"
        time.sleep(0.02)


def test_indexer_adds_documents_and_reports_failures(tmp_path, standard_pdf, model):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    indexer = Indexer(library_factory=factory)
    good, bad = indexer.submit(ADD, "ACME-STD-1234.pdf", file_bytes=standard_pdf), indexer.submit(ADD, "bad.pdf", file_bytes=b"x")
    wait(indexer)
    assert good.status == DONE and "Added ACME-STD-1234" in good.result and not good.warning
    assert bad.status == FAILED
    library = factory()
    assert len(library.list_documents()) == 1 and library.unfinished_jobs() == []


def test_jobs_left_by_an_earlier_run_are_resumed(tmp_path, standard_pdf, extractor, model, monkeypatch):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    library = factory()
    # An upload that was queued but never started, and a document stopped while its passages were being read
    library.queue_job(ADD, "queued.pdf", sha256=library.store_pdf(make_pdf([["1 SCOPE", "1.1 Purpose. A second document."]])))
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: 1 / 0)
    doc, _ = library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)
    library.queue_job(ADD, "ACME-STD-1234.pdf", sha256=doc.sha256)
    assert doc.embedding_model == ""

    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: fake_vectors(texts))
    indexer = Indexer(library_factory=factory)          # The app starting again
    wait(indexer)
    assert [j.status for j in indexer.jobs] == [DONE, DONE]
    documents = factory().list_documents()
    assert len(documents) == 2 and all(d.embedding_model == config.EMBEDDING_ID for d in documents)
    assert factory().unfinished_jobs() == []


def test_a_document_still_being_added_counts_as_busy(tmp_path, standard_pdf, model, monkeypatch):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    reading, carry_on = threading.Event(), threading.Event()

    def slow(texts, on_progress=None):
        reading.set()
        carry_on.wait(30)
        return fake_vectors(texts)

    monkeypatch.setattr(semantic, "embed_passages", slow)
    indexer = Indexer(library_factory=factory)
    indexer.submit(ADD, "ACME-STD-1234.pdf", file_bytes=standard_pdf)
    assert reading.wait(30)
    document = factory().list_documents()[0]            # Already there, and searchable by words
    assert document.embedding_model == "" and indexer.pending_doc_ids() == {document.id}
    carry_on.set()
    wait(indexer)
    assert indexer.pending_doc_ids() == set()


def test_embed_job(tmp_path, standard_pdf, extractor, model, monkeypatch):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: 1 / 0)
    doc, _ = factory().add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: fake_vectors(texts))
    indexer = Indexer(library_factory=factory)
    job = indexer.submit(EMBED, doc.title, doc_id=doc.id)
    wait(indexer)
    assert job.status == DONE and factory().get_document(doc.id).embedding_model == config.EMBEDDING_ID


def test_code_scan_job(tmp_path):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    codebase = CodeStore(factory().conn).add(str(Path(__file__).parent / "codebase"), "Demo")
    indexer = Indexer(library_factory=factory)
    job = indexer.submit(CODE, codebase.name, doc_id=codebase.id)
    assert indexer.pending_codebases() == {codebase.id} and indexer.pending_doc_ids() == set()
    wait(indexer)
    assert job.status == DONE and "10 files" in job.result
    assert CodeStore(factory().conn).get(codebase.id).symbol_count == 33


# ---- Evaluation harness ------------------------------------------------------------------------

def test_evaluation_reports_ranks_per_mode(library, doc, monkeypatch):
    monkeypatch.setattr(config, "MEANING_MIN_SIMILARITY", 0.3)
    lines = []
    summary = evaluate(library, [
        {"query": "how long must calibration records be kept", "expect": [{"clause": "4.2", "text": "retained"}]},
        {"query": "lubricant replaced", "expect": [{"document": "ACME", "clause": "20.1"}]},
        {"query": "nothing about this anywhere", "expect": [{"clause": "99"}]},
    ], k=5, out=lines.append)
    assert summary["combined"]["found"] == pytest.approx(2 / 3) and summary["combined"]["mrr"] > 0.5
    assert len(lines) > 5
