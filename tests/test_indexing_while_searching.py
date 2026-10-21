"""Searching while a large document is indexed (ADR-033): the model shared fairly, every stage reported."""
import threading
import time

import numpy as np

from conftest import fake_vectors
from src import config
from src.extractor import pdf as pdf_extractor
from src.search import semantic
from src.search.indexer import ADD, Indexer
from src.search.library import Library, SAVING, UNDERSTANDING


class FakeModel:
    """Stands in for the sentence-transformer: records each call and takes a moment, like the real one."""
    def __init__(self, delay: float = 0.0):
        self.calls = []
        self.delay = delay

    def encode(self, texts, batch_size=None, **_):
        self.calls.append(list(texts))
        time.sleep(self.delay)
        return fake_vectors(texts)


def test_the_indexer_hands_the_model_four_passages_at_a_time(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(semantic, "get_model", lambda: model)
    monkeypatch.setattr(config, "EMBEDDING_DIMENSIONS", 256)
    vectors = semantic.embed_passages([f"passage {i}" for i in range(10)])
    assert config.EMBEDDING_BATCH == 4
    assert [len(call) for call in model.calls] == [4, 4, 2] and vectors.shape == (10, 256)


def test_a_search_arriving_during_indexing_is_encoded_before_the_next_batch(monkeypatch):
    model = FakeModel(delay=0.05)
    monkeypatch.setattr(semantic, "get_model", lambda: model)
    monkeypatch.setattr(config, "EMBEDDING_DIMENSIONS", 256)
    indexing = threading.Thread(target=lambda: semantic.embed_passages([f"passage {i}" for i in range(24)]))
    indexing.start()
    while len(model.calls) < 2:          # Indexing is under way
        time.sleep(0.005)
    semantic.embed_query("how long must calibration records be kept")
    indexing.join()
    order = [call[0][:6] for call in model.calls]
    # The query went in after the batch that was running, not after the whole run of passages
    assert order.index("query:") <= 3 and order.count("query:") == 1 and len(model.calls) == 7


def test_the_model_keeps_half_the_threads_and_at_least_two():
    assert [semantic.indexing_threads(n) for n in (1, 2, 3, 4, 8, 16)] == [1, 2, 2, 2, 4, 8]


def test_every_indexing_stage_reports_with_its_count(library, extractor, standard_pdf, model):
    stages = []
    library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor,
                         lambda stage, done, total: stages.append((stage, done, total)))
    order = list(dict.fromkeys(stage for stage, _, _ in stages))
    assert order == [pdf_extractor.READING, pdf_extractor.CLAUSES, pdf_extractor.XREFS, pdf_extractor.IDENTIFIERS,
                     SAVING, UNDERSTANDING]
    for stage in order:   # Each ends complete, and its total is a real count
        last = [(done, total) for s, done, total in stages if s == stage][-1]
        assert last[0] == last[1] > 0, (stage, last)


def test_a_job_left_by_an_earlier_run_says_it_was_resumed_and_whether_it_starts_over(tmp_path, standard_pdf, extractor, model, monkeypatch):
    factory = lambda: Library(tmp_path / "library.db", tmp_path / "pdfs")
    library = factory()
    # One stopped before its pages were read (nothing in the library yet), one stopped during its meaning vectors
    fresh = library.queue_job(ADD, "fresh.pdf", sha256=library.store_pdf(standard_pdf + b"\n% fresh"))
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: 1 / 0)
    doc, _ = library.add_document(standard_pdf, "ACME-STD-1234.pdf", extractor)
    partly = library.queue_job(ADD, "ACME-STD-1234.pdf", sha256=doc.sha256)
    monkeypatch.setattr(semantic, "embed_passages", lambda texts, on_progress=None: fake_vectors(texts))

    started = threading.Event()
    monkeypatch.setattr(Indexer, "_start_worker", lambda self: started.set())   # Look before anything runs
    indexer = Indexer(library_factory=factory)
    jobs = {j.id: j for j in indexer.jobs}
    assert (jobs[fresh].resumed, jobs[fresh].restarted) == (True, True)
    assert (jobs[partly].resumed, jobs[partly].restarted) == (True, False)
