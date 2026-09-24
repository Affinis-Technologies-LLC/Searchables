"""Collections of pinned passages, tables and figures, stored alongside the library."""
import hashlib
import json
import sqlite3
from datetime import datetime
from typing import List, Optional, Set

from src.models import Collection, Pin, TextBlock

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pins (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    -- SET NULL: a pin keeps its copied text and citation after its document is deleted
    doc_id        INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    pin_key       TEXT NOT NULL,
    doc_title     TEXT NOT NULL,
    page          INTEGER NOT NULL,
    page_label    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    label         TEXT NOT NULL,
    clause        TEXT NOT NULL,
    citation      TEXT NOT NULL,
    text          TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    query         TEXT NOT NULL DEFAULT '',
    added_at      TEXT NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    table_json    TEXT,
    UNIQUE (collection_id, pin_key)
);
"""

DEFAULT_COLLECTION = "My research"


def pin_key(block: TextBlock) -> str:
    """Identifies a passage across re-indexing, which renumbers blocks but not documents, pages or text."""
    return hashlib.sha1(f"{block.doc_id}|{block.page}|{block.text}".encode()).hexdigest()


class CollectionStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.executescript(_SCHEMA)

    # ---- Collections -----------------------------------------------------------------------

    def list_collections(self) -> List[Collection]:
        rows = self.conn.execute(
            "SELECT c.id, c.name, COUNT(p.id) AS pin_count FROM collections c "
            "LEFT JOIN pins p ON p.collection_id = c.id GROUP BY c.id ORDER BY c.name COLLATE NOCASE"
        ).fetchall()
        return [Collection(row["id"], row["name"], row["pin_count"]) for row in rows]

    def ensure_default(self) -> int:
        """The id of some collection, creating the default one when there are none."""
        row = self.conn.execute("SELECT id FROM collections ORDER BY id LIMIT 1").fetchone()
        return row["id"] if row else self.create(DEFAULT_COLLECTION)

    def create(self, name: str) -> int:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Give the collection a name.")
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO collections (name, created_at) VALUES (?, ?)",
                    (name, datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"There's already a collection called “{name}”.") from None
        return cur.lastrowid

    def rename(self, collection_id: int, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Give the collection a name.")
        try:
            with self.conn:
                self.conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
        except sqlite3.IntegrityError:
            raise ValueError(f"There's already a collection called “{name}”.") from None

    def delete(self, collection_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))

    # ---- Pins ------------------------------------------------------------------------------

    def add_pin(
        self,
        collection_id: int,
        block: TextBlock,
        doc_title: str,
        citation: str,
        query: str = "",
        table: Optional[dict] = None,
    ) -> None:
        """Pins a block, copying what's needed to cite and export it. Pinning twice is a no-op."""
        x0, y0, x1, y1 = block.bbox or (None, None, None, None)
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO pins (collection_id, doc_id, pin_key, doc_title, page, page_label, kind, "
                "label, clause, citation, text, query, added_at, x0, y0, x1, y1, table_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (collection_id, block.doc_id, pin_key(block), doc_title, block.page, block.display_page,
                 block.kind, block.label, block.clause, citation, block.text, query.strip(),
                 datetime.now().isoformat(timespec="seconds"), x0, y0, x1, y1,
                 json.dumps(table) if table else None),
            )

    def remove_pin_for(self, collection_id: int, block: TextBlock) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM pins WHERE collection_id = ? AND pin_key = ?", (collection_id, pin_key(block))
            )

    def remove_pin(self, pin_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM pins WHERE id = ?", (pin_id,))

    def update_note(self, pin_id: int, note: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE pins SET note = ? WHERE id = ?", (note.strip(), pin_id))

    def pinned_keys(self, collection_id: int) -> Set[str]:
        rows = self.conn.execute("SELECT pin_key FROM pins WHERE collection_id = ?", (collection_id,)).fetchall()
        return {row[0] for row in rows}

    def pins(self, collection_id: int) -> List[Pin]:
        rows = self.conn.execute(
            "SELECT * FROM pins WHERE collection_id = ? ORDER BY added_at, id", (collection_id,)
        ).fetchall()
        return [
            Pin(
                id=row["id"], collection_id=row["collection_id"], doc_id=row["doc_id"], doc_title=row["doc_title"],
                page=row["page"], page_label=row["page_label"], kind=row["kind"], label=row["label"],
                clause=row["clause"], citation=row["citation"], text=row["text"], note=row["note"],
                query=row["query"], added_at=row["added_at"],
                bbox=(row["x0"], row["y0"], row["x1"], row["y1"]) if row["x0"] is not None else None,
                table=json.loads(row["table_json"]) if row["table_json"] else None,
            )
            for row in rows
        ]
