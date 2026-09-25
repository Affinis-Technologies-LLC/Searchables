"""Persistent document library: PDFs on disk, blocks and a full-text index in SQLite."""
import hashlib
import math
from collections import Counter
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src import config
from src.extractor.identifiers import family_of, identifier_key, parent_key, summarize_families
from src.extractor.objects import parse_caption, standard_pattern
from src.extractor.pdf import PDFExtractor, ProgressCallback
from src.extractor.provisions import NOTE, PERMISSION, RECOMMENDATION, REQUIREMENT, classify_provision
from src.models import (CrossRef, Document, ExtractedDocument, IdentifierFamily, IdentifierHit, RelatedIdentifier,
                        RelatedIdentifiers, RelatedPassage, ResolvedRef, SearchResult, TableData, Term, TextBlock)
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
CREATE TABLE IF NOT EXISTS identifier_occurrences (
    id       INTEGER PRIMARY KEY,
    doc_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    key      TEXT NOT NULL,     -- Matching form: "FLD2041"
    value    TEXT NOT NULL,     -- As written: "FLD 2041"
    family   TEXT NOT NULL,     -- Shape: "FLD#"
    role     TEXT NOT NULL,     -- heading, caption, table, text
    row      INTEGER            -- Table row for role "table" (0 = header row)
);
CREATE INDEX IF NOT EXISTS identifier_key ON identifier_occurrences(key, doc_id);
CREATE INDEX IF NOT EXISTS identifier_block ON identifier_occurrences(block_id);
CREATE INDEX IF NOT EXISTS identifier_family ON identifier_occurrences(doc_id, family);
-- One row per shape per document. user_enabled (NULL = follow discovery) survives re-indexing.
CREATE TABLE IF NOT EXISTS identifier_families (
    doc_id          INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    family          TEXT NOT NULL,
    display         TEXT NOT NULL,
    distinct_values INTEGER NOT NULL,
    passages        INTEGER NOT NULL,
    examples        TEXT NOT NULL,
    auto_enabled    INTEGER NOT NULL,
    user_enabled    INTEGER,
    PRIMARY KEY (doc_id, family)
);
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
        self.conn.executemany(
            "INSERT INTO identifier_occurrences (doc_id, block_id, key, value, family, role, row) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(doc_id, first_id + o.block_id, o.key, o.value, o.family, o.role, o.row) for o in extracted.identifiers],
        )
        families = summarize_families(extracted.identifiers, doc_id)
        self.conn.executemany(
            "INSERT INTO identifier_families (doc_id, family, display, distinct_values, passages, examples, auto_enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(doc_id, family) DO UPDATE SET "
            "display = excluded.display, distinct_values = excluded.distinct_values, passages = excluded.passages, "
            "examples = excluded.examples, auto_enabled = excluded.auto_enabled",
            [(f.doc_id, f.family, f.display, f.distinct_values, f.passages, f.examples, int(f.auto_enabled))
             for f in families],
        )
        # Families gone after re-indexing are dropped, unless the user chose a setting for them
        present = [f.family for f in families]
        placeholders = ", ".join("?" * len(present)) or "''"  # NOT IN () is invalid SQL
        self.conn.execute(
            f"DELETE FROM identifier_families WHERE doc_id = ? AND user_enabled IS NULL "
            f"AND family NOT IN ({placeholders})",
            [doc_id, *present],
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

    # ---- Identifiers -----------------------------------------------------------------------

    def identifier_families(self, doc_id: int) -> List[IdentifierFamily]:
        rows = self.conn.execute(
            "SELECT * FROM identifier_families WHERE doc_id = ? ORDER BY auto_enabled DESC, passages DESC", (doc_id,)
        ).fetchall()
        return [
            IdentifierFamily(
                doc_id=row["doc_id"], family=row["family"], display=row["display"],
                distinct_values=row["distinct_values"], passages=row["passages"], examples=row["examples"],
                auto_enabled=bool(row["auto_enabled"]),
                user_enabled=None if row["user_enabled"] is None else bool(row["user_enabled"]),
            )
            for row in rows
        ]

    def enabled_families(self, doc_id: int) -> set:
        return {f.family for f in self.identifier_families(doc_id) if f.enabled}

    def set_family_enabled(self, doc_id: int, family: str, enabled: Optional[bool]) -> None:
        """Overrides discovery for one family; None returns it to automatic."""
        with self.conn:
            self.conn.execute(
                "UPDATE identifier_families SET user_enabled = ? WHERE doc_id = ? AND family = ?",
                (None if enabled is None else int(enabled), doc_id, family),
            )

    def reset_families(self, doc_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE identifier_families SET user_enabled = NULL WHERE doc_id = ?", (doc_id,))

    # ---- Identifier search ----------------------------------------------------------------

    def _scope(self, doc_ids: Optional[Sequence[int]], kinds: Optional[Sequence[str]] = None,
               provisions: Optional[Sequence[str]] = None, alias: str = "o") -> Tuple[str, list]:
        """SQL conditions for the sidebar's search scope, on occurrences (`alias`) and blocks (b)."""
        where, params = "", []
        if doc_ids:
            where += f" AND {alias}.doc_id IN ({', '.join('?' * len(doc_ids))})"
            params.extend(doc_ids)
        if kinds:
            where += f" AND b.kind IN ({', '.join('?' * len(kinds))})"
            params.extend(kinds)
        if provisions:
            where += f" AND b.provision IN ({', '.join('?' * len(provisions))})"
            params.extend(provisions)
        return where, params

    def _matching_keys(self, key: str, include_children: bool, doc_ids: Optional[Sequence[int]]) -> List[str]:
        """The identifier itself, plus the identifiers extending it when asked ("K3.5" → "K3.5C1")."""
        if not include_children:
            return [key]
        where, params = self._scope(doc_ids)
        rows = self.conn.execute(
            f"SELECT DISTINCT o.key FROM identifier_occurrences o WHERE o.key LIKE ? {where}",
            [key.replace("%", "").replace("_", "") + "%", *params],
        ).fetchall()
        return [key] + [r[0] for r in rows if r[0] != key and parent_key(r[0], {key}) == key]

    def identifier_search(
        self,
        text: str,
        include_children: bool = False,
        doc_ids: Optional[Sequence[int]] = None,
        kinds: Optional[Sequence[str]] = None,
        provisions: Optional[Sequence[str]] = None,
    ) -> List[IdentifierHit]:
        """
        Every passage containing the identifier (case, spaces and hyphens ignored), grouped by role:
        headings and captions first, then table rows, rules, and other mentions.
        """
        keys = self._matching_keys(identifier_key(text), include_children, doc_ids)
        where, params = self._scope(doc_ids, kinds, provisions)
        rows = self.conn.execute(
            f"""
            SELECT o.role, o.row, o.value, b.*, d.title AS doc_title
            FROM identifier_occurrences o
            JOIN blocks b ON b.id = o.block_id
            JOIN documents d ON d.id = o.doc_id
            WHERE o.key IN ({', '.join('?' * len(keys))}) {where}
            ORDER BY d.title COLLATE NOCASE, b.seq
            """,
            [*keys, *params],
        ).fetchall()

        hits: Dict[int, dict] = {}
        for row in rows:
            hit = hits.setdefault(row["id"], {"block": _row_to_block(row), "doc_title": row["doc_title"],
                                              "roles": set(), "rows": set(), "values": set()})
            hit["roles"].add(row["role"])
            hit["values"].add(row["value"])
            if row["row"] is not None:
                hit["rows"].add(row["row"])

        results = [
            IdentifierHit(block=h["block"], doc_title=h["doc_title"], group=_identifier_group(h["block"], h["roles"], h["values"]),
                          values=tuple(sorted(h["values"], key=len, reverse=True)), rows=tuple(sorted(h["rows"])))
            for h in hits.values()
        ]
        return sorted(results, key=lambda r: IDENTIFIER_GROUPS.index(r.group))  # Stable: keeps document order

    def related_identifiers(self, text: str, include_children: bool = False,
                            doc_ids: Optional[Sequence[int]] = None) -> RelatedIdentifiers:
        """
        Identifiers connected to this one: its parent and sub-identifiers, and those appearing in
        the same table row (strongest) or the same passage. Only switched-on families are used.
        """
        key = identifier_key(text)
        keys = self._matching_keys(key, include_children, doc_ids)
        where, params = self._scope(doc_ids, alias="o1")
        enabled = ("JOIN identifier_families f ON f.doc_id = o2.doc_id AND f.family = o2.family "
                   "AND COALESCE(f.user_enabled, f.auto_enabled) = 1")
        rows = self.conn.execute(
            f"""
            SELECT o2.key, o2.value,
                   SUM(CASE WHEN o1.row IS NOT NULL AND o2.row = o1.row THEN 1 ELSE 0 END) AS same_row,
                   SUM(CASE WHEN o1.row IS NULL AND o2.row IS NULL THEN 1 ELSE 0 END) AS same_passage
            FROM identifier_occurrences o1
            JOIN identifier_occurrences o2 ON o2.block_id = o1.block_id AND o2.key != o1.key
            {enabled}
            WHERE o1.key IN ({', '.join('?' * len(keys))}) {where}
            GROUP BY o2.key, o2.value
            """,
            [*keys, *params],
        ).fetchall()

        scores: Dict[str, dict] = {}
        for row in rows:
            if row["key"] in keys:
                continue
            entry = scores.setdefault(row["key"], {"values": Counter(), "same_row": 0, "same_passage": 0})
            entry["values"][row["value"]] += row["same_row"] + row["same_passage"]
            entry["same_row"] += row["same_row"]
            entry["same_passage"] += row["same_passage"]
        related = sorted(
            (RelatedIdentifier(key=k, value=e["values"].most_common(1)[0][0], same_row=e["same_row"],
                               same_passage=e["same_passage"])
             for k, e in scores.items() if e["same_row"] or e["same_passage"]),
            key=lambda r: (-(r.same_row * config.SAME_ROW_WEIGHT + r.same_passage), r.value),
        )[:config.RELATED_IDENTIFIERS]

        known = self._known_keys(doc_ids)
        parent = parent_key(key, known)
        children = sorted(k for k in known if k != key and parent_key(k, known) == key)
        return RelatedIdentifiers(
            parent=self._display_value(parent) if parent else None,
            children=tuple(self._display_value(k) for k in children),
            related=tuple(related),
        )

    def _known_keys(self, doc_ids: Optional[Sequence[int]]) -> set:
        """Identifier keys of switched-on families (the vocabulary for parents and suggestions)."""
        where, params = self._scope(doc_ids)
        rows = self.conn.execute(
            "SELECT DISTINCT o.key FROM identifier_occurrences o JOIN identifier_families f "
            "ON f.doc_id = o.doc_id AND f.family = o.family AND COALESCE(f.user_enabled, f.auto_enabled) = 1 "
            f"WHERE 1 = 1 {where}",
            params,
        ).fetchall()
        return {r[0] for r in rows}

    def _display_value(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM identifier_occurrences WHERE key = ? GROUP BY value ORDER BY COUNT(*) DESC LIMIT 1",
            (key,),
        ).fetchone()
        return row[0] if row else key

    def identifier_suggestions(self, text: str, doc_ids: Optional[Sequence[int]] = None,
                               limit: int = config.IDENTIFIER_SUGGESTIONS) -> List[str]:
        """Known identifiers starting with (or else containing) what was typed, most used first."""
        key = identifier_key(text).replace("%", "").replace("_", "")
        if not key:
            return []
        where, params = self._scope(doc_ids)
        enabled = ("JOIN identifier_families f ON f.doc_id = o.doc_id AND f.family = o.family "
                   "AND COALESCE(f.user_enabled, f.auto_enabled) = 1")
        for pattern in (key + "%", "%" + key + "%"):
            rows = self.conn.execute(
                f"SELECT o.key, COUNT(*) AS uses FROM identifier_occurrences o {enabled} "
                f"WHERE o.key LIKE ? AND o.key != ? {where} GROUP BY o.key ORDER BY uses DESC LIMIT ?",
                [pattern, key, *params, limit],
            ).fetchall()
            if rows:
                return [self._display_value(r[0]) for r in rows]
        return []

    def identifier_pages(self, doc_id: int, text: str, include_children: bool = False) -> List[int]:
        keys = self._matching_keys(identifier_key(text), include_children, [doc_id])
        rows = self.conn.execute(
            f"SELECT DISTINCT b.page FROM identifier_occurrences o JOIN blocks b ON b.id = o.block_id "
            f"WHERE o.doc_id = ? AND o.key IN ({', '.join('?' * len(keys))}) ORDER BY b.page",
            [doc_id, *keys],
        ).fetchall()
        return [r[0] for r in rows]

    def identifier_values_on_page(self, doc_id: int, page: int, text: str,
                                  include_children: bool = False) -> Dict[int, List[str]]:
        """Block id → the identifier's written forms in that block, for highlighting."""
        keys = self._matching_keys(identifier_key(text), include_children, [doc_id])
        rows = self.conn.execute(
            f"SELECT o.block_id, o.value FROM identifier_occurrences o JOIN blocks b ON b.id = o.block_id "
            f"WHERE o.doc_id = ? AND b.page = ? AND o.key IN ({', '.join('?' * len(keys))})",
            [doc_id, page, *keys],
        ).fetchall()
        found: Dict[int, List[str]] = {}
        for row in rows:
            found.setdefault(row[0], [])
            if row[1] not in found[row[0]]:
                found[row[0]].append(row[1])
        return found

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
        identifier_families = self.enabled_families(doc_id)
        for row in rows:
            if (row["kind"], row["target"]) in seen:
                continue
            seen.add((row["kind"], row["target"]))
            ref = self.resolve(doc_id, CrossRef(row["block_id"], row["kind"], row["target"]))
            if ref.doc_id is None and ref.ref.kind == "clause":
                continue
            # "FLD 2041" looks like a document designation, but in a document where it's one of many
            # values of an identifier family it's an identifier; show it only if it opens a document
            if ref.doc_id is None and ref.ref.kind == "standard" and family_of(ref.ref.target) in identifier_families:
                continue
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
        return ResolvedRef(ref=ref, doc_id=doc_id, page=block.page, bbox=block.bbox, block_id=block.id)

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
                first = self.conn.execute("SELECT id FROM blocks WHERE doc_id = ? ORDER BY seq LIMIT 1", (doc.id,)).fetchone()
                return ResolvedRef(ref=ref, doc_id=doc.id, page=1, doc_title=doc.title, block_id=first[0] if first else None)
        return ResolvedRef(ref=ref, doc_id=None)

    # ---- Related passages ------------------------------------------------------------------

    def get_block(self, block_id: int) -> Optional[TextBlock]:
        row = self.conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
        return _row_to_block(row) if row else None

    def related_passages(self, block: TextBlock, terms: Sequence[Term] = (),
                         limit: int = config.RELATED_PER_GROUP) -> Dict[str, List[RelatedPassage]]:
        """
        Passages connected to `block`, by group (see RELATED_GROUPS), each with the reason. A passage
        appears once, in the first group that finds it. `terms` are the defined terms `block` uses.
        """
        seen = {block.id}
        titles = {d.id: d.title for d in self.list_documents()}
        groups: Dict[str, List[RelatedPassage]] = {}

        def add(group: str, candidates: Iterable[Tuple[int, str]]) -> None:
            found = []
            for block_id, reason in candidates:
                if block_id in seen or len(found) >= limit:
                    continue
                other = self.get_block(block_id)
                if other:
                    seen.add(block_id)
                    found.append(RelatedPassage(other, titles.get(other.doc_id, ""), reason))
            if found:
                groups[group] = found

        add("references", self._outgoing_links(block))
        add("referenced_by", self._incoming_links(block))
        add("identifiers", self._shared_identifiers(block))
        add("terms", self._shared_terms(block, terms))
        add("similar", self._similar_wording(block))
        return groups

    def _outgoing_links(self, block: TextBlock) -> List[Tuple[int, str]]:
        identifier_families = self.enabled_families(block.doc_id)
        links = []
        for row in self.conn.execute("SELECT kind, target FROM xrefs WHERE block_id = ? ORDER BY id", (block.id,)):
            ref = self.resolve(block.doc_id, CrossRef(block.id, row["kind"], row["target"]))
            if ref.block_id is None:
                continue  # Not in the library, or a dotted number that isn't a clause
            if ref.ref.kind == "standard" and family_of(ref.ref.target) in identifier_families:
                continue
            name = f"Clause {ref.ref.target}" if ref.ref.kind == "clause" else ref.ref.target
            links.append((ref.block_id, f"References {name}"))
        return links

    def _incoming_links(self, block: TextBlock) -> List[Tuple[int, str]]:
        """Passages referring to this passage's table/figure, or to the clause it heads."""
        targets = set()
        if block.is_object and block.label:
            targets.add((block.kind, block.label))
        heads_clause = block.kind == "heading" or (block.clause_num and block.text.startswith(block.clause_num))
        if heads_clause and block.clause_num:
            targets.add(("clause", block.clause_num))
            if block.clause_num.startswith(("Annex", "Appendix")):
                targets.add(("annex", block.clause_num))
        if not targets:
            return []
        condition = " OR ".join("(x.kind = ? AND x.target = ?)" for _ in targets)
        rows = self.conn.execute(
            f"SELECT x.block_id, x.kind, x.target FROM xrefs x WHERE x.doc_id = ? AND x.block_id != ? AND ({condition}) "
            f"ORDER BY x.block_id",
            [block.doc_id, block.id, *[v for pair in sorted(targets) for v in pair]],
        ).fetchall()
        return [(r["block_id"], f"Refers to {'Clause ' + r['target'] if r['kind'] == 'clause' else r['target']}")
                for r in rows]

    def _shared_identifiers(self, block: TextBlock) -> List[Tuple[int, str]]:
        """Other passages with this passage's identifiers; rarer shared identifiers count for more."""
        keys = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT o.key FROM identifier_occurrences o JOIN identifier_families f ON f.doc_id = o.doc_id "
            "AND f.family = o.family AND COALESCE(f.user_enabled, f.auto_enabled) = 1 WHERE o.block_id = ?",
            (block.id,),
        )]
        if not keys:
            return []
        marks = ", ".join("?" * len(keys))
        spread = dict(self.conn.execute(
            f"SELECT key, COUNT(DISTINCT block_id) FROM identifier_occurrences WHERE key IN ({marks}) GROUP BY key", keys
        ).fetchall())
        shared: Dict[int, set] = {}
        for row in self.conn.execute(
            f"SELECT DISTINCT block_id, key FROM identifier_occurrences WHERE key IN ({marks}) AND block_id != ?",
            [*keys, block.id],
        ):
            shared.setdefault(row[0], set()).add(row[1])
        scored = sorted(shared.items(), key=lambda kv: -sum(1 / math.log(1 + spread[k]) for k in kv[1]))
        return [(block_id, "Shares " + ", ".join(self._display_value(k) for k in sorted(found)[:3])
                 + (f" and {len(found) - 3} more" if len(found) > 3 else ""))
                for block_id, found in scored]

    def _shared_terms(self, block: TextBlock, terms: Sequence[Term]) -> List[Tuple[int, str]]:
        """The definitions of the terms this passage uses, then other passages using the same terms."""
        links, using = [], {}
        for term in terms:
            row = self.conn.execute(
                "SELECT id FROM blocks WHERE doc_id = ? AND clause_num = ? ORDER BY (kind = 'heading') DESC, seq LIMIT 1",
                (term.doc_id, term.clause_num),
            ).fetchone()
            if row:
                links.append((row[0], f"Defines “{term.term}”"))
            fts_query = build_fts_query(" OR ".join(f'"{name}"' for name in term.names))
            if not fts_query:
                continue
            for other in self.conn.execute(
                "SELECT b.id FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid "
                "WHERE blocks_fts MATCH ? AND b.doc_id = ? AND b.id != ? ORDER BY bm25(blocks_fts) LIMIT 50",
                (fts_query, block.doc_id, block.id),
            ):
                using.setdefault(other[0], []).append(term.term)
        for block_id, names in sorted(using.items(), key=lambda kv: -len(kv[1])):
            links.append((block_id, "Uses " + ", ".join(f"“{n}”" for n in names[:3])))
        return links

    def _similar_wording(self, block: TextBlock) -> List[Tuple[int, str]]:
        """
        "More like this" with the full-text index: the passage's distinctive words as an OR query,
        ranked by BM25 (rarer shared words count for more). Needs a few shared words to count.
        """
        words = [w for w in dict.fromkeys(re.findall(r"[a-z][a-z-]{3,}", block.text.lower())) if w not in _COMMON_WORDS]
        words = sorted(words, key=len, reverse=True)[:config.SIMILAR_QUERY_WORDS]
        fts_query = build_fts_query(" OR ".join(f'"{w}"' for w in words)) if words else None
        if not fts_query:
            return []
        links = []
        for row in self.conn.execute(
            "SELECT b.id, highlight(blocks_fts, 0, ?, ?) AS marked FROM blocks_fts JOIN blocks b ON b.id = blocks_fts.rowid "
            "WHERE blocks_fts MATCH ? AND b.id != ? AND b.kind != 'heading' ORDER BY bm25(blocks_fts) LIMIT 40",
            (_HIT_START, _HIT_END, fts_query, block.id),
        ):
            shared = list(dict.fromkeys(m.lower() for m in _MARKED_SPAN.findall(row["marked"])))
            if len(shared) >= config.SIMILAR_MIN_SHARED_WORDS:
                links.append((row["id"], "Similar wording: " + ", ".join(shared[:4])))
        return links

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


# Groups of related passages, in display (and priority) order
RELATED_GROUPS = {
    "references": "References",
    "referenced_by": "Referenced by",
    "identifiers": "Shares identifiers",
    "terms": "Defined terms",
    "similar": "Similar wording",
}
# Too common in standards to make two passages "similar"
_COMMON_WORDS = set("""
shall should must will would could that this these those with from have been into such than then them they their
there where when which while also each other only same more most less least many much some used using uses based
within without between including include includes following given specified accordance according requirements
requirement document documents standard standards clause clauses table tables figure figures annex appendix section
paragraph note notes example examples see apply applies applicable general specific provided shown described
""".split())


# Display order of identifier results: where it's defined, table rows, rules, then other mentions
IDENTIFIER_GROUPS = ["defined", "table", "rule", "mention"]
IDENTIFIER_GROUP_TITLES = {
    "defined": "Headings and captions",
    "table": "Table rows",
    "rule": "Rules (shall / should / may)",
    "mention": "Other mentions",
}


def _identifier_group(block: TextBlock, roles: set, values: Sequence[str]) -> str:
    if roles & {"heading", "caption"}:
        return "defined"
    # A run-in heading ("4.2 Message K3.5. The K3.5 message…") names its subject in the clause title
    if (block.clause_num and block.text.startswith(block.clause_num)
            and any(value in block.clause_title for value in values)):
        return "defined"
    if "table" in roles:
        return "table"
    if block.provision in (REQUIREMENT, RECOMMENDATION, PERMISSION):
        return "rule"
    return "mention"


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
