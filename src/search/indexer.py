"""
Background indexing: adding, re-indexing and embedding documents without blocking the app.

Jobs are processed one at a time by a worker thread with its own database connection, so searches,
pins and page views carry on meanwhile. Each job's stage and progress are kept for the app to show.

The queue is also kept in the library (uploads are stored as soon as they're submitted), so jobs an
earlier run of the app didn't finish are picked up again when it starts.
"""
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from src import config
from src.code.store import CodeStore
from src.extractor.pdf import PDFExtractor
from src.search.library import Library

ADD, REINDEX, EMBED, CODE = "add", "reindex", "embed", "code"
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Job:
    id: int
    kind: str                       # ADD, REINDEX, EMBED or CODE
    name: str                       # File name, document title or codebase name
    sha256: Optional[str] = None    # ADD: the upload, as stored in the library folder
    doc_id: Optional[int] = None    # The document; for CODE, the codebase
    resumed: bool = False           # Left unfinished by an earlier run of the app
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
    _queue: Optional[Library] = None        # Connection for the stored queue, used under the lock
    _worker: Optional[threading.Thread] = None

    def __post_init__(self) -> None:
        with self._lock:
            self._queue = self.library_factory()
            for row in self._queue.unfinished_jobs():
                self.jobs.append(Job(id=row["id"], kind=row["kind"], name=row["name"], sha256=row["sha256"],
                                     doc_id=row["doc_id"], resumed=True))
            self._start_worker()

    def submit(self, kind: str, name: str, file_bytes: Optional[bytes] = None, doc_id: Optional[int] = None) -> Job:
        with self._lock:
            # The upload is stored before the job is queued, so neither is lost if the app stops
            sha256 = self._queue.store_pdf(file_bytes) if file_bytes is not None else None
            job = Job(id=self._queue.queue_job(kind, name, sha256, doc_id), kind=kind, name=name,
                      sha256=sha256, doc_id=doc_id)
            self.jobs.append(job)
            self._start_worker()
        return job

    def _start_worker(self) -> None:
        waiting = any(j.status == QUEUED for j in self.jobs)
        if waiting and (self._worker is None or not self._worker.is_alive()):
            self._worker = threading.Thread(target=self._run, name="searchables-indexer", daemon=True)
            self._worker.start()

    def active(self) -> List[Job]:
        with self._lock:
            return [j for j in self.jobs if j.status in (QUEUED, RUNNING)]

    def finished(self) -> List[Job]:
        with self._lock:
            return [j for j in self.jobs if j.status in (DONE, FAILED)]

    def pending_doc_ids(self) -> set:
        """
        Documents with a job waiting or running (so buttons can be disabled), including a document
        being added: it's in the library once its pages are read, while its passages are still being read.
        """
        active = [j for j in self.active() if j.kind != CODE]
        ids = {j.doc_id for j in active if j.doc_id is not None}
        with self._lock:
            added = [self._queue.document_by_sha(j.sha256) for j in active if j.sha256]
        return ids | {doc.id for doc in added if doc}

    def pending_codebases(self) -> set:
        """Codebases with a scan waiting or running."""
        return {j.doc_id for j in self.active() if j.kind == CODE}

    def _next(self) -> Optional[Job]:
        with self._lock:
            job = next((j for j in self.jobs if j.status == QUEUED), None)
            if job is None:
                self._worker = None  # This worker is about to end: the next submit starts another
            return job

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
                status = DONE
            except Exception as e:  # Any failure is reported on the job; the worker carries on
                status = FAILED
                job.result = str(e) or e.__class__.__name__
            try:
                library.finish_job(job.id)
            except sqlite3.Error:
                pass  # Still queued in the library: looked at again when the app next starts
            job.finished_at = time.time()
            job.status = status

    @staticmethod
    def _process(library: Library, extractor: PDFExtractor, job: Job, progress) -> None:
        if job.kind == ADD:
            doc, extracted = library.add_stored_document(job.sha256, job.name, extractor, progress)
            if extracted is None and job.resumed and doc.embedding_model != config.EMBEDDING_ID:
                # Stopped while its passages were being read: carry on from the vectors already saved
                library.embed_document(doc.id, progress)
                job.result = f"Added {doc.title}: {doc.page_count} pages, {doc.block_count} passages"
                return
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
        elif job.kind == CODE:
            found = CodeStore(library.conn).index(job.doc_id, progress)
            job.result = (f"Scanned {job.name}: {found['files']:,} files, {found['symbols']:,} symbols "
                          f"({found['changed']:,} read, {found['removed']:,} removed)")


def _warnings(embedding_model: str, unreadable_pages: List[int]) -> str:
    notes = []
    if not embedding_model:
        notes.append("Meaning search isn't available for it yet: the embedding model couldn't be loaded "
                     "(it's downloaded once, which needs an internet connection). Use “Add meaning search” "
                     "in the Library view once it's available.")
    if unreadable_pages:
        pages = ", ".join(map(str, unreadable_pages[:20]))
        notes.append(f"Scanned pages {pages} could not be read and aren't searchable.")
    return " ".join(notes)
