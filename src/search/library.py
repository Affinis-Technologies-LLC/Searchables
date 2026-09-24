"""Persistent document library: PDFs on disk, blocks and a full-text index in SQLite."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src import config
from src.extractor.objects import parse_caption, standard_pattern
from src.extractor.pdf import PDFExtractor, ProgressCallback
from src.extractor.provisions import NOTE, PERMISSION, RECOMMENDATION, REQUIREMENT, classify_provision
from src.models import CrossRef, Document, ExtractedDocument, ResolvedRef, SearchResult, TableData, TextBlock
from src.search.query import build_fts_query
from src.utils.formatting import marked_to_html

# Control characters never appear in extracted text, so they are safe highlight markers
_HIT_START, _HIT_END = "\x02", "\x03"
_MARKED_SPAN = re.compile(f"{_HIT_START}(.*?){_HIT_END}", re.DOTALL)
_SNIPPET_TOKENS = 40  # Tables index every cell; results show this many tokens around the hits

# Result kinds the sidebar filter offers; headings are grouped with text
CONTENT_KINDS = {"Text": ("text", "heading"), "Tables": ("table",), "Figures": ("figure",)}
PROVISION_FILTERS = {
    "Requirements (shall)": REQUIREMENT,
    "Recommendations (should)": RECOMMENDATION,
    "Permissions (may)": PERMISSION,
    "Notes & examples": NOTE,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    sha256          TEXT NOT NULL UNIQUE,
    page_count      INTEGER NOT NULL,
    block_count     INTEGER NOT NULL,
    ocr_pages       INTEGER NOT NULL DEFAULT 0,
    added_at        TEXT NOT NULL,
    extract_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS blocks (
    id           INTEGER PRIMARY KEY,
    doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    page         INTEGER NOT NULL,
    page_label   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    clause_num   TEXT NOT NULL,
    clause_title TEXT NOT NULL,
    clause_path  TEXT NOT NULL,
    text         TEXT NOT NULL,
    word_count   INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    label        TEXT NOT NULL DEFAULT '',
    provision    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS blocks_doc_page ON blocks(doc_id, page, seq);
-- Porter stemming: "calibrate" matches "calibration"; rowid mirrors blocks.id
CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5(
    text, tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS tables (
    block_id INTEGER PRIMARY KEY REFERENCES blocks(id) ON DELETE CASCADE,
    columns  TEXT NOT NULL,   -- JSON list of header cells
    rows     TEXT NOT NULL    -- JSON list of rows
);
CREATE TABLE IF NOT EXISTS xrefs (
    id       INTEGER PRIMARY KEY,
    doc_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL,
    target   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS xrefs_target ON xrefs(doc_id, kind, target);
CREATE INDEX IF NOT EXISTS xrefs_block ON xrefs(block_id);
CREATE TABLE IF NOT EXISTS search_history (
    query       TEXT PRIMARY KEY,
    searched_at TEXT NOT NULL
);
"""

# Columns added after the first release; CREATE TABLE IF NOT EXISTS won't add them to an existing library
_ADDED_COLUMNS = {
    "documents": [("extract_version", "INTEGER NOT NULL DEFAULT 1")],
    "blocks": [("label", "TEXT NOT NULL DEFAULT ''"), ("provision", "TEXT NOT NULL DEFAULT ''")],
}


class Library:
    def __init__(self, db_path: Path = config.DB_PATH, pdf_dir: Path = config.PDF_DIR):
        self.pdf_dir = pdf_dir
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        # Streamlit reruns on different threads; the app is single-user so one shared connection is fine
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self.conn.executescript(_SCHEMA)

    def _migrate(self) -> None:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if not existing:
                continue  # Fresh library: the schema creates the table with every column
            for name, definition in columns:
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    if (table, name) == ("blocks", "provision"):
                        self._backfill_provisions()
        self.conn.commit()

    def _backfill_provisions(self) -> None:
        # Classification only needs the stored text, so older libraries get it without re-indexing
        rows = self.conn.execute("SELECT id, text FROM blocks WHERE kind = 'text'").fetchall()
        self.conn.executemany(
            "UPDATE blocks SET provision = ? WHERE id = ?",
            [(classify_provision(row["text"]), row["id"]) for row in rows],
        )

    # ---- Documents -------------------------------------------------------------------------

    def add_document(
        self,
        file_bytes: bytes,
        filename: str,
        extractor: PDFExtractor,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Tuple[Document, Optional[ExtractedDocument]]:
        """
        Extracts and indexes a PDF. Returns (document, extraction details), with details None
        when the same file is already in the library. Raises ValueError for unusable PDFs.
        """
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        existing = self._document_by_sha(sha256)
        if existing:
            return existing, None

        extracted = self._extract(file_bytes, filename, extractor, on_progress)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO documents (title, filename, sha256, page_count, block_count, ocr_pages, added_at, "
                "extract_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (extracted.title, filename, sha256, extracted.page_count, len(extracted.blocks),
                 len(extracted.ocr_pages), datetime.now().isoformat(timespec="seconds"), config.EXTRACTOR_VERSION),
            )
            self._store_extraction(cur.lastrowid, extracted)

        # Keep the original PDF for page rendering; written after the commit so a failed index leaves no orphan
        self.pdf_path(sha256).write_bytes(file_bytes)
        return self._document_by_sha(sha256), extracted

    def reindex_document(
        self,
        doc_id: int,
        extractor: PDFExtractor,
        on_progress: Optional[ProgressCallback] = None,
    ) -> ExtractedDocument:
        """Re-extracts a document from its stored PDF with the current extractor, keeping its title."""
        doc = self.get_document(doc_id)
        if doc is None:
            raise ValueError("That document is no longer in the library.")
        path = self.pdf_path(doc.sha256)
        if not path.exists():
            raise ValueError(f"The stored PDF for {doc.title} is missing; delete it and add the file again.")

        extracted = self._extract(path.read_bytes(), doc.filename, extractor, on_progress)
        with self.conn:
            self._delete_index(doc_id)
            self.conn.execute(
                "UPDATE documents SET page_count = ?, block_count = ?, ocr_pages = ?, extract_version = ? WHERE id = ?",
                (extracted.page_count, len(extracted.blocks), len(extracted.ocr_pages), config.EXTRACTOR_VERSION, doc_id),
            )
            self._store_extraction(doc_id, extracted)
        return extracted

    @staticmethod
    def _extract(file_bytes: bytes, filename: str, extractor: PDFExtractor,
                 on_progress: Optional[ProgressCallback]) -> ExtractedDocument:
        extracted = extractor.extract(file_bytes, filename, on_progress)
        if not extracted.blocks:
            raise ValueError(
                f"No extractable text found in {filename}. "
                "It may be a scan and Tesseract OCR is not available."
            )
        return extracted

    def _store_extraction(self, doc_id: int, extracted: ExtractedDocument) -> None:
        """Writes blocks, index, tables and cross-references. Call inside a transaction."""
        first_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM blocks").fetchone()[0]
        # Extracted ids are positions (0, 1, 2…), so the stored id is first_id + local id
        rows = [
            (first_id + b.id, doc_id, b.id, b.page, b.page_label, b.kind, b.clause_num, b.clause_title,
             b.clause_path, b.text, b.word_count, *(b.bbox or (None, None, None, None)), b.label, b.provision)
            for b in extracted.blocks
        ]
        self.conn.executemany(
            "INSERT INTO blocks (id, doc_id, seq, page, page_label, kind, clause_num, clause_title, clause_path, "
            "text, word_count, x0, y0, x1, y1, label, provision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.executemany("INSERT INTO blocks_fts (rowid, text) VALUES (?, ?)", [(r[0], r[9]) for r in rows])
        self.conn.executemany(
            "INSERT INTO tables (block_id, columns, rows) VALUES (?, ?, ?)",
            [(first_id + t.block_id, json.dumps(t.columns), json.dumps(t.rows)) for t in extracted.tables],
        )
        self.conn.executemany(
            "INSERT INTO xrefs (doc_id, block_id, kind, target) VALUES (?, ?, ?, ?)",
            [(doc_id, first_id + x.block_id, x.kind, x.target) for x in extracted.xrefs],
        )

    def _delete_index(self, doc_id: int) -> None:
        # FTS5 tables have no foreign keys, so their rows go explicitly; the rest cascade from blocks
        self.conn.execute("DELETE FROM blocks_fts WHERE rowid IN (SELECT id FROM blocks WHERE doc_id = ?)", (doc_id,))
        self.conn.execute("DELETE FROM blocks WHERE doc_id = ?", (doc_id,))

    def list_documents(self) -> List[Document]:
        rows = self.conn.execute("SELECT * FROM documents ORDER BY title COLLATE NOCASE").fetchall()
        return [Document(**dict(row)) for row in rows]

    def outdated_documents(self) -> List[Document]:
        """Documents indexed before the current extractor, missing its newer features."""
        return [d for d in self.list_documents() if d.extract_version < config.EXTRACTOR_VERSION]

    def rename_document(self, doc_id: int, title: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE documents SET title = ? WHERE id = ?", (title.strip(), doc_id))

    def delete_document(self, doc_id: int) -> None:
        row = self.conn.execute("SELECT sha256 FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return
        with self.conn:
            self._delete_index(doc_id)
            self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.pdf_path(row["sha256"]).unlink(missing_ok=True)

    def pdf_path(self, sha256: str) -> Path:
        return self.pdf_dir / f"{sha256}.pdf"

    def get_document(self, doc_id: int) -> Optional[Document]:
        row = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return Document(**dict(row)) if row else None

    def _document_by_sha(self, sha256: str) -> Optional[Document]:
        row = self.conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
        return Document(**dict(row)) if row else None

    # ---- Search ----------------------------------------------------------------------------

    def search(
        self,
        query_text: str,
        doc_ids: Optional[Sequence[int]] = None,
        limit: int = config.DEFAULT_MAX_RESULTS,
        document_order: bool = False,
        kinds: Optional[Sequence[str]] = None,
        provisions: Optional[Sequence[str]] = None,
    ) -> Tuple[List[SearchResult], int]:
        """
        Returns (results, total_matches). Relevance order uses BM25; document order lists hits
        as they appear (by document, then position) for reading through every mention.
        `kinds` limits results to block kinds ("text", "heading", "table", "figure"); `provisions`
        to passages classified as "requirement", "recommendation", "permission" or "note".
        Raises ValueError when the query has nothing searchable.
        """
        fts_query = build_fts_query(query_text)
        if not fts_query:
            raise ValueError("Enter at least one word to search for.")

        where = "blocks_fts MATCH ?"
        params: list = [fts_query]
        if doc_ids:
            where += f" AND b.doc_id IN ({', '.join('?' * len(doc_ids))})"
            params.extend(doc_ids)
        if kinds:
            where += f" AND b.kind IN ({', '.join('?' * len(kinds))})"
            params.extend(kinds)
        if provisions:
            where += f" AND b.provision IN ({', '.join('?' * len(provisions))})"
            params.extend(provisions)

        total = self.conn.execute(
            f"SELECT COUNT(*) FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid WHERE {where}",
            params,
        ).fetchone()[0]

        order = "d.title COLLATE NOCASE, b.seq" if document_order else "score"
        rows = self.conn.execute(
            f"""
            SELECT b.*, d.title AS doc_title,
                   bm25(blocks_fts) * (CASE WHEN b.kind = 'heading' THEN ? ELSE 1.0 END) AS score,
                   highlight(blocks_fts, 0, ?, ?) AS marked,
                   snippet(blocks_fts, 0, ?, ?, '…', {_SNIPPET_TOKENS}) AS snippet
            FROM blocks_fts
            JOIN blocks b ON b.id = blocks_fts.rowid
            JOIN documents d ON d.id = b.doc_id
            WHERE {where}
            ORDER BY {order}
            LIMIT ?
            """,
            [config.HEADING_SCORE_WEIGHT, _HIT_START, _HIT_END, _HIT_START, _HIT_END, *params, limit],
        ).fetchall()

        results = [
            SearchResult(
                block=_row_to_block(row),
                score=-row["score"],  # FTS5 bm25() is negative; flip so higher is better
                rank=rank,
                # A table block holds every cell, so show the neighbourhood of the hits instead
                highlighted_text=marked_to_html(row["snippet" if row["kind"] == "table" else "marked"],
                                                _HIT_START, _HIT_END),
                doc_title=row["doc_title"],
            )
            for rank, row in enumerate(rows, 1)
        ]
        return results, total

    def hit_pages(self, query_text: str, doc_id: int) -> List[int]:
        """Pages of one document that contain a match, in page order."""
        fts_query = build_fts_query(query_text)
        if not fts_query:
            return []
        rows = self.conn.execute(
            "SELECT DISTINCT b.page FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid "
            "WHERE blocks_fts MATCH ? AND b.doc_id = ? ORDER BY b.page",
            (fts_query, doc_id),
        ).fetchall()
        return [row[0] for row in rows]

    def page_matches(self, query_text: str, doc_id: int, page: int) -> Dict[int, str]:
        """Matching blocks on one page: block id → HTML with hits wrapped in <mark>."""
        return {
            block_id: marked_to_html(marked, _HIT_START, _HIT_END)
            for block_id, marked in self._page_marked(query_text, doc_id, page)
        }

    def page_hit_terms(self, query_text: str, doc_id: int, page: int) -> List[str]:
        """
        The exact words FTS matched on a page ("calibrated", "Calibration" for "calibrate"),
        so the page image can highlight stemmed forms and phrases, not just what was typed.
        """
        terms = set()
        for _, marked in self._page_marked(query_text, doc_id, page):
            terms.update(t.strip() for t in _MARKED_SPAN.findall(marked))
        return sorted((t for t in terms if t), key=len, reverse=True)

    def _page_marked(self, query_text: str, doc_id: int, page: int) -> List[Tuple[int, str]]:
        fts_query = build_fts_query(query_text)
        if not fts_query:
            return []
        rows = self.conn.execute(
            "SELECT b.id, highlight(blocks_fts, 0, ?, ?) FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid "
            "WHERE blocks_fts MATCH ? AND b.doc_id = ? AND b.page = ?",
            (_HIT_START, _HIT_END, fts_query, doc_id, page),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def document_blocks(self, doc_id: int) -> List[TextBlock]:
        rows = self.conn.execute("SELECT * FROM blocks WHERE doc_id = ? ORDER BY seq", (doc_id,)).fetchall()
        return [_row_to_block(row) for row in rows]

    def page_blocks(self, doc_id: int, page: int) -> List[TextBlock]:
        rows = self.conn.execute(
            "SELECT * FROM blocks WHERE doc_id = ? AND page = ? ORDER BY seq", (doc_id, page)
        ).fetchall()
        return [_row_to_block(row) for row in rows]

    # ---- Search history --------------------------------------------------------------------

    def record_search(self, query_text: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO search_history (query, searched_at) VALUES (?, ?) "
                "ON CONFLICT(query) DO UPDATE SET searched_at = excluded.searched_at",
                (query_text.strip(), datetime.now().isoformat(timespec="seconds")),
            )

    def recent_searches(self, limit: int = config.RECENT_SEARCHES) -> List[str]:
        rows = self.conn.execute(
            "SELECT query FROM search_history ORDER BY searched_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [row[0] for row in rows]

    # ---- Tables ----------------------------------------------------------------------------

    def table_parts(self, block: TextBlock) -> List[Tuple[TextBlock, TableData]]:
        """
        A table and its continuations ("Table 5 (continued)" on later pages), in order.
        Uncaptioned tables have no label to join on, so they stand alone.
        """
        if block.label:
            rows = self.conn.execute(
                "SELECT b.*, t.columns, t.rows FROM blocks b JOIN tables t ON t.block_id = b.id "
                "WHERE b.doc_id = ? AND b.label = ? ORDER BY b.seq",
                (block.doc_id, block.label),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT b.*, t.columns, t.rows FROM blocks b JOIN tables t ON t.block_id = b.id WHERE b.id = ?",
                (block.id,),
            ).fetchall()
        return [
            (_row_to_block(row), TableData(row["id"], json.loads(row["columns"]), json.loads(row["rows"])))
            for row in rows
        ]

    # ---- Cross-references ------------------------------------------------------------------

    def page_refs(self, doc_id: int, page: int) -> List[ResolvedRef]:
        """
        References made on a page, resolved to where they point. Clause references that don't
        resolve are dropped: a dotted number with no matching clause is usually a value, not a reference.
        """
        rows = self.conn.execute(
            "SELECT x.block_id, x.kind, x.target FROM xrefs x JOIN blocks b ON b.id = x.block_id "
            "WHERE b.doc_id = ? AND b.page = ? ORDER BY b.seq, x.id",
            (doc_id, page),
        ).fetchall()
        seen, resolved = set(), []
        for row in rows:
            if (row["kind"], row["target"]) in seen:
                continue
            seen.add((row["kind"], row["target"]))
            ref = self.resolve(doc_id, CrossRef(row["block_id"], row["kind"], row["target"]))
            if ref.doc_id is not None or ref.ref.kind != "clause":
                resolved.append(ref)
        return resolved

    def resolve(self, doc_id: int, ref: CrossRef) -> ResolvedRef:
        if ref.kind == "standard":
            return self._resolve_standard(doc_id, ref)
        if ref.kind in ("table", "figure"):
            row = self.conn.execute(
                "SELECT * FROM blocks WHERE doc_id = ? AND label = ? ORDER BY seq LIMIT 1", (doc_id, ref.target)
            ).fetchone() or self._caption_block(doc_id, ref.target)
        else:  # Clause or annex: prefer the heading itself over the first passage under it
            row = self.conn.execute(
                "SELECT * FROM blocks WHERE doc_id = ? AND clause_num = ? "
                "ORDER BY (kind = 'heading') DESC, seq LIMIT 1",
                (doc_id, ref.target),
            ).fetchone()
        if row is None:
            return ResolvedRef(ref=ref, doc_id=None)
        block = _row_to_block(row)
        return ResolvedRef(ref=ref, doc_id=doc_id, page=block.page, bbox=block.bbox)

    def _caption_block(self, doc_id: int, label: str) -> Optional[sqlite3.Row]:
        """Fallback for tables/figures that weren't detected as objects: their caption as plain text."""
        for row in self.conn.execute(
            "SELECT * FROM blocks WHERE doc_id = ? AND text LIKE ? ORDER BY seq", (doc_id, f"{label}%")
        ):
            caption = parse_caption(row["text"])
            if caption and caption.label == label:
                return row
        return None

    def _resolve_standard(self, doc_id: int, ref: CrossRef) -> ResolvedRef:
        pattern = standard_pattern(ref.target)
        for doc in self.list_documents():
            haystack = f"{doc.title} {doc.filename}".lower().replace("_", " ")
            if doc.id != doc_id and pattern.search(haystack):
                return ResolvedRef(ref=ref, doc_id=doc.id, page=1, doc_title=doc.title)
        return ResolvedRef(ref=ref, doc_id=None)

    def referenced_from(self, doc_id: int, page: int) -> List[Tuple[CrossRef, TextBlock]]:
        """
        Passages elsewhere in the document that refer to something on this page: its clauses,
        annexes, tables or figures.
        """
        blocks = self.page_blocks(doc_id, page)
        targets = {("clause", b.clause_num) for b in blocks if b.kind == "heading" and b.clause_num}
        targets |= {("annex", b.clause_num) for b in blocks if b.kind == "heading" and b.clause_num.startswith("Annex")}
        targets |= {(b.kind, b.label) for b in blocks if b.is_object and b.label}
        if not targets:
            return []

        condition = " OR ".join("(x.kind = ? AND x.target = ?)" for _ in targets)
        rows = self.conn.execute(
            f"SELECT x.kind AS ref_kind, x.target, b.* FROM xrefs x JOIN blocks b ON b.id = x.block_id "
            f"WHERE x.doc_id = ? AND b.page != ? AND ({condition}) ORDER BY b.seq",
            [doc_id, page, *[v for pair in sorted(targets) for v in pair]],
        ).fetchall()
        return [(CrossRef(row["id"], row["ref_kind"], row["target"]), _row_to_block(row)) for row in rows]


def _row_to_block(row: sqlite3.Row) -> TextBlock:
    bbox = (row["x0"], row["y0"], row["x1"], row["y1"]) if row["x0"] is not None else None
    return TextBlock(
        id=row["id"],
        doc_id=row["doc_id"],
        page=row["page"],
        page_label=row["page_label"],
        text=row["text"],
        word_count=row["word_count"],
        kind=row["kind"],
        label=row["label"],
        clause_num=row["clause_num"],
        clause_title=row["clause_title"],
        clause_path=row["clause_path"],
        bbox=bbox,
        provision=row["provision"],
    )
