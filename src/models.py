from dataclasses import dataclass, field
from typing import List, Optional, Tuple

BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class TextBlock:
    id: int
    page: int                   # 1-based physical page index
    text: str
    word_count: int
    doc_id: Optional[int] = None
    page_label: str = ""        # Printed page number ("iv", "23"); falls back to physical page
    kind: str = "text"          # "text", "heading", "table" or "figure"
    label: str = ""             # Tables/figures: "Table 1", "Figure A.2"
    clause_num: str = ""        # "7.3.2", "A.1", "Annex B"
    clause_title: str = ""      # "Design inputs"
    clause_path: str = ""       # "7 Operation › 7.3 Design › 7.3.2 Design inputs"
    bbox: Optional[BBox] = None # Position on the page, in PDF points
    provision: str = ""         # "requirement", "recommendation", "permission", "note" or ""

    @property
    def clause(self) -> str:
        return " ".join(part for part in (self.clause_num, self.clause_title) if part)

    @property
    def is_object(self) -> bool:
        return self.kind in ("table", "figure")

    @property
    def display_page(self) -> str:
        return self.page_label or str(self.page)


@dataclass(frozen=True)
class Document:
    id: int
    title: str
    filename: str
    sha256: str
    page_count: int
    block_count: int
    ocr_pages: int
    added_at: str
    extract_version: int = 1    # Extractor version that indexed it; older ones lack newer features
    embedding_model: str = ""   # Model that made its meaning vectors ("" = none yet)


@dataclass(frozen=True)
class TableData:
    block_id: int               # The "table" block that represents it in search results
    columns: List[str]
    rows: List[List[str]]


@dataclass(frozen=True)
class CrossRef:
    block_id: int               # Block the reference appears in
    kind: str                   # "table", "figure", "clause", "annex" or "standard"
    target: str                 # Normalized: "Table 1", "4.2.1", "Annex A", "ISO 4126-1"


@dataclass(frozen=True)
class ResolvedRef:
    ref: CrossRef
    doc_id: Optional[int]       # None when the target isn't in the library
    page: Optional[int] = None
    bbox: Optional[BBox] = None
    doc_title: str = ""
    block_id: Optional[int] = None  # The passage it points to (a document's first passage for documents)


@dataclass(frozen=True)
class Collection:
    id: int
    name: str
    pin_count: int = 0


@dataclass(frozen=True)
class Pin:
    """
    A saved passage, table or figure. It keeps its own copy of the text, citation and table data,
    so it survives re-indexing (which renumbers blocks) and deletion of its document.
    """
    id: int
    collection_id: int
    doc_id: Optional[int]       # None once the document is deleted
    doc_title: str
    page: int
    page_label: str
    kind: str
    label: str
    clause: str
    citation: str
    text: str
    note: str
    query: str                  # The search that found it
    added_at: str
    bbox: Optional[BBox] = None
    table: Optional[dict] = None  # {"columns": [...], "rows": [[...]]} for tables


@dataclass(frozen=True)
class Term:
    """An entry in a standard's "Terms and definitions" clause."""
    term: str                   # "set pressure"
    synonyms: Tuple[str, ...]   # Other names given in the entry ("opening pressure")
    clause_num: str             # "3.1"
    definition: str
    doc_id: int
    page: int
    page_label: str
    bbox: Optional[BBox] = None

    @property
    def names(self) -> Tuple[str, ...]:
        return (self.term, *self.synonyms)


@dataclass(frozen=True)
class ClauseText:
    """Everything under one clause of a document, for comparing editions."""
    key: str                    # Clause number, or the title for unnumbered clauses ("Foreword")
    num: str
    title: str
    text: str
    page: int
    bbox: Optional[BBox]
    provisions: Tuple[int, int, int]  # Counts of shall, should, may


@dataclass(frozen=True)
class ClauseDiff:
    status: str                 # "unchanged", "changed", "added", "removed"
    old: Optional[ClauseText]
    new: Optional[ClauseText]
    similarity: float = 1.0     # Word-level, 0–1
    renumbered: bool = False    # Matched by title or content under a different number

    @property
    def provisions_changed(self) -> bool:
        return (self.old.provisions if self.old else (0, 0, 0)) != (self.new.provisions if self.new else (0, 0, 0))


@dataclass(frozen=True)
class IdentifierOccurrence:
    block_id: int               # Local id at extraction; the stored block id afterwards
    value: str                  # As written: "FLD 2041"
    key: str                    # Matching form: "FLD2041"
    family: str                 # Shape: "FLD#"
    role: str                   # "heading", "caption", "table" or "text"
    row: Optional[int] = None   # Table row (0 = header row) for role "table"


@dataclass(frozen=True)
class IdentifierFamily:
    doc_id: int
    family: str                 # Shape used for matching: "K#.#C#"
    display: str                # Shape as usually written: "FLD #"
    distinct_values: int
    passages: int
    examples: str
    auto_enabled: bool          # Discovery's own verdict
    user_enabled: Optional[bool] = None  # The user's override, kept across re-indexing

    @property
    def enabled(self) -> bool:
        return self.auto_enabled if self.user_enabled is None else self.user_enabled


@dataclass(frozen=True)
class IdentifierHit:
    """A passage containing a searched identifier."""
    block: TextBlock
    doc_title: str
    group: str                  # "defined", "table", "rule" or "mention"
    values: Tuple[str, ...]     # How the identifier is written there, longest first
    rows: Tuple[int, ...] = ()  # Table rows containing it (0 = header row)


@dataclass(frozen=True)
class RelatedIdentifier:
    key: str
    value: str
    same_row: int               # Times it shares a table row with the searched identifier
    same_passage: int           # Times it shares a passage


@dataclass(frozen=True)
class RelatedIdentifiers:
    parent: Optional[str]
    children: Tuple[str, ...]
    related: Tuple[RelatedIdentifier, ...]


@dataclass(frozen=True)
class RelatedPassage:
    block: TextBlock
    doc_title: str
    reason: str                 # Why it's related: "References Table I", "Shares K3.5, FLD 2041"…
    similarity: Optional[float] = None       # Same-topic matches: meaning similarity (0–1)
    findings: Tuple = ()                     # Same-topic matches: research.assess.Finding items
    closest: Optional[Tuple[str, str]] = None  # Same-topic matches: best (this passage, that passage) sentences


@dataclass
class ExtractedDocument:
    title: str
    page_count: int
    blocks: List[TextBlock] = field(default_factory=list)
    tables: List[TableData] = field(default_factory=list)     # block_id refers to TextBlock.id (local)
    xrefs: List[CrossRef] = field(default_factory=list)       # block_id refers to TextBlock.id (local)
    identifiers: List[IdentifierOccurrence] = field(default_factory=list)  # block_id is local too
    ocr_pages: List[int] = field(default_factory=list)         # Pages whose text came from OCR
    unreadable_pages: List[int] = field(default_factory=list)  # Scanned pages OCR could not handle


@dataclass(frozen=True)
class SearchResult:
    block: TextBlock
    score: float
    rank: int
    highlighted_text: Optional[str] = None  # HTML-safe text with <mark> around matched terms
    doc_title: str = ""
    match: str = "keyword"      # "keyword", "meaning" (found only by meaning) or "both"
    similarity: Optional[float] = None  # Meaning similarity to the query (0–1), when matched by meaning

    @property
    def citation(self) -> str:
        parts = [self.doc_title, self.block.label or self.block.clause, f"p. {self.block.display_page}"]
        return ", ".join(part for part in parts if part)
