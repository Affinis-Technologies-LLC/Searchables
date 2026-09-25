"""
Background indexing: adding, re-indexing and embedding documents without blocking the app.

Jobs are processed one at a time by a worker thread with its own database connection, so searches,
pins and page views carry on meanwhile. Each job's stage and progress are kept for the app to show.
"""
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.extractor.pdf import PDFExtractor
from src.search.library import Library

ADD, REINDEX, EMBED = "add", "reindex", "embed"
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Job:
    id: int
    kind: str                       # ADD, REINDEX or EMBED
    name: str                       # File name or document title
    file_bytes: Optional[bytes] = None
    doc_id: Optional[int] = None
    status: str = QUEUED
    stage: str = "Waiting"
    done: int = 0
    total: int = 0
    result: str = ""                # Outcome shown to the user
    warning: str = ""
    finished_at: float = 0.0

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


@dataclass
class Indexer:
    library_factory: type = Library
    jobs: List[Job] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _worker: Optional[threading.Thread] = None

    def submit(self, kind: str, name: str, file_bytes: Optional[bytes] = None, doc_id: Optional[int] = None) -> Job:
        job = Job(id=next(self._ids), kind=kind, name=name, file_bytes=file_bytes, doc_id=doc_id)
        with self._lock:
            self.jobs.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="searchables-indexer", daemon=True)
                self._worker.start()
        return job

    def active(self) -> List[Job]:
        with self._lock:
            return [j for j in self.jobs if j.status in (QUEUED, RUNNING)]

    def finished(self) -> List[Job]:
        with self._lock:
            return [j for j in self.jobs if j.status in (DONE, FAILED)]

    def pending_doc_ids(self) -> set:
        """Documents with a re-index or embed job waiting or running (so buttons can be disabled)."""
        return {j.doc_id for j in self.active() if j.doc_id is not None}

    def _next(self) -> Optional[Job]:
        with self._lock:
            return next((j for j in self.jobs if j.status == QUEUED), None)

    def _run(self) -> None:
        library = self.library_factory()  # This thread's own connection
        extractor = PDFExtractor()
        while True:
            job = self._next()
            if job is None:
                return
            job.status = RUNNING

            def progress(stage: str, done: int, total: int, job: Job = job) -> None:
                job.stage, job.done, job.total = stage, done, total

            try:
                self._process(library, extractor, job, progress)
                job.status = DONE
            except Exception as e:  # Any failure is reported on the job; the worker carries on
                job.status = FAILED
                job.result = str(e) or e.__class__.__name__
            finally:
                job.file_bytes = None  # Free the upload's memory
                job.finished_at = time.time()

    @staticmethod
    def _process(library: Library, extractor: PDFExtractor, job: Job, progress) -> None:
        if job.kind == ADD:
            doc, extracted = library.add_document(job.file_bytes, job.name, extractor, progress)
            if extracted is None:
                job.result = f"{job.name} is already in the library as “{doc.title}”."
                return
            notes = [f"{doc.page_count} pages", f"{doc.block_count} passages"]
            if extracted.tables:
                notes.append(f"{len(extracted.tables)} tables")
            if extracted.ocr_pages:
                count = len(extracted.ocr_pages)
                notes.append(f"{count} scanned page{'s' if count != 1 else ''} read with OCR")
            job.result = f"Added {doc.title}: " + ", ".join(notes)
            job.warning = _warnings(doc.embedding_model, extracted.unreadable_pages)
        elif job.kind == REINDEX:
            extracted = library.reindex_document(job.doc_id, extractor, progress)
            doc = library.get_document(job.doc_id)
            job.result = (f"Re-indexed {job.name}: {len(extracted.blocks)} passages, {len(extracted.tables)} tables, "
                          f"{len(extracted.xrefs)} cross-references")
            job.warning = _warnings(doc.embedding_model if doc else "", extracted.unreadable_pages)
        elif job.kind == EMBED:
            count = library.embed_document(job.doc_id, progress)
            job.result = f"Added meaning search to {job.name}: {count} passages"


def _warnings(embedding_model: str, unreadable_pages: List[int]) -> str:
    notes = []
    if not embedding_model:
        notes.append("Meaning search isn't available for it yet: the embedding model couldn't be loaded "
                     "(it's downloaded once, which needs an internet connection). Use “Add meaning search” "
                     "in the Library tab once it's available.")
    if unreadable_pages:
        pages = ", ".join(map(str, unreadable_pages[:20]))
        notes.append(f"Scanned pages {pages} could not be read and aren't searchable.")
    return " ".join(notes)
