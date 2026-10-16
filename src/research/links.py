"""
Fixing a PDF's dead links (ADR-031). Every link annotation and bookmark is checked at the raw
object level (PyMuPDF's get_links() reports a GoTo to a missing page object as page 1), the
reference text under a link is parsed by the extractor's rule and placed by the document's own
structure, and a fixed copy is written with only link annotations and the outline changed.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pymupdf

from src.extractor.objects import find_xrefs, parse_caption
from src.extractor.pdf import PDFExtractor, destination_of
from src.extractor.structure import _level_of, match_outline
from src.models import BBox, ExtractedDocument, TextBlock

OK, DEAD, WRONG, UNRESOLVED, EXTERNAL = "ok", "dead", "wrong page", "unresolved", "external"
UNCHECKED = "unchecked"             # A bookmark that resolves but names no heading the extractor knows (ADR-032)
STATES = (OK, DEAD, WRONG, UNRESOLVED, EXTERNAL)


@dataclass
class Link:
    id: int
    page: int                           # 1-based
    rect: BBox
    text: str                           # The words under the link
    kind: str                           # "goto", "named" or "uri"
    target: str                         # As found: "page 7", "named destination 'x'", a URI, or why it's dead
    state: str
    reference: str = ""                 # The reference read under the link ("Table 5.1-2"), if any
    proposed_page: Optional[int] = None
    proposed_point: Optional[Tuple[float, float]] = None
    xref: int = 0
    page_size: Tuple[float, float] = (0.0, 0.0)


@dataclass
class Bookmark:
    id: int
    level: int
    title: str
    page: Optional[int]                 # None when the destination is gone
    state: str
    proposed_page: Optional[int] = None
    proposed_point: Optional[Tuple[float, float]] = None
    proposed_title: Optional[str] = None   # The heading's own text, when the bookmark was matched by number and differs (ADR-032)


@dataclass
class Unbookmarked:
    page: int
    title: str
    level: int


@dataclass
class Unlinked:
    page: int
    rect: BBox
    reference: str
    target_page: int
    target_point: Tuple[float, float]


@dataclass
class Report:
    filename: str
    page_count: int
    refused: str = ""                   # Why nothing can be done, or ""
    links: List[Link] = field(default_factory=list)
    bookmarks: List[Bookmark] = field(default_factory=list)
    unbookmarked: List[Unbookmarked] = field(default_factory=list)   # Headings no bookmark names (ADR-032)
    unlinked: List[Unlinked] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)


# ---- Reading the file -----------------------------------------------------------------------------

def _refusal(doc: pymupdf.Document) -> str:
    if doc.needs_pass:
        return "The PDF needs a password to open; nothing can be checked."
    if not (doc.permissions & pymupdf.PDF_PERM_ANNOTATE):
        return "The PDF's permissions forbid changing its annotations, which is what a link is."
    if doc.get_sigflags() > 0:
        return "The PDF is signed; changing a link would invalidate the signature."
    return ""


def _line_under(words: Sequence[tuple], rect: pymupdf.Rect) -> Tuple[str, str]:
    """(the words inside the rectangle, the whole line they sit on)."""
    inside = [w for w in words if pymupdf.Rect(w[:4]).intersects(rect) and pymupdf.Rect(w[:4]).intersect(rect).width > 1]
    if not inside:
        return "", ""
    lines = {(w[5], w[6]) for w in inside}
    line = [w for w in words if (w[5], w[6]) in lines]
    return " ".join(w[4].strip(".,;:()") for w in inside), " ".join(w[4] for w in line)


def _number(target: str) -> str:
    return target.split(" ", 1)[1] if " " in target else target


def _reference(text: str, line: str) -> Tuple[str, str]:
    """The (kind, target) of the reference the link's words belong to, from the references on its line."""
    for kind, target in find_xrefs(line):
        if kind != "standard" and _number(target) in text:
            return kind, target
    return "", ""


def _locate(extracted: ExtractedDocument, kind: str, target: str) -> Optional[TextBlock]:
    """Where the document puts a table, figure, clause or annex: the library's resolution rule, in memory."""
    if kind in ("table", "figure"):
        for block in extracted.blocks:
            if block.label == target:
                return block
        for block in extracted.blocks:
            if block.text.startswith(target):
                caption = parse_caption(block.text)
                if caption and caption.label == target:
                    return block
        return None
    if kind in ("clause", "annex"):
        candidates = [b for b in extracted.blocks if b.clause_num == target]
        headings = [b for b in candidates if b.kind == "heading"]
        return (headings or candidates or [None])[0]
    return None


def _point(block: TextBlock) -> Tuple[float, float]:
    return (block.bbox[0], block.bbox[1]) if block.bbox else (0.0, 0.0)


def _heading_title(block: TextBlock) -> str:
    """A heading as a bookmark title: its number and title, else its first line."""
    return block.clause or " ".join(block.text.split("\n", 1)[0].split())


def outline_from_headings(extracted: ExtractedDocument) -> List[list]:
    """The outline written whole from the headings: levels from the clause numbers, made consistent for PDF readers."""
    toc, previous = [], 0
    for block in extracted.blocks:
        if block.kind != "heading":
            continue
        level = min(_level_of(block.clause_num) if block.clause_num else 1, previous + 1)
        toc.append([level, _heading_title(block), block.page, {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(*_point(block)), "zoom": 0}])
        previous = level
    return toc


# ---- The report -----------------------------------------------------------------------------------

def check(file_bytes: bytes, filename: str, extractor: PDFExtractor) -> Report:
    """Every link and bookmark with its state and, where the document itself says where it should go, the fix."""
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Failed to open PDF document: {e}") from e
    with doc:
        report = Report(filename, doc.page_count, _refusal(doc))
        if report.refused:
            return report
        extracted = extractor.extract(file_bytes, filename)
        page_xrefs = {doc.page_xref(i): i for i in range(doc.page_count)}
        next_id = 1
        for index in range(doc.page_count):
            page = doc[index]
            words = page.get_text("words")
            covered: List[pymupdf.Rect] = []
            for raw in page.get_links():
                rect = pymupdf.Rect(raw["from"])
                covered.append(rect)
                kind, target, page_index, why = destination_of(doc, raw["xref"], page_xrefs)
                text, line = _line_under(words, rect)
                link = Link(next_id, index + 1, tuple(rect), text, kind, target, OK, xref=raw["xref"],
                            page_size=(page.rect.width, page.rect.height))
                next_id += 1
                if kind == "uri":
                    link.state = EXTERNAL
                elif kind == "other":
                    link.state = OK
                else:
                    ref_kind, ref_target = _reference(text, line)
                    link.reference = ref_target
                    block = _locate(extracted, ref_kind, ref_target) if ref_target else None
                    if why == "dead":
                        link.state = DEAD if block else UNRESOLVED
                    elif block and block.page != page_index + 1:
                        link.state = WRONG
                    if block and link.state in (DEAD, WRONG):
                        link.proposed_page, link.proposed_point = block.page, _point(block)
                report.links.append(link)
            # References in the text with no link over them
            for block in extracted.blocks:
                if block.page != index + 1 or not block.bbox:
                    continue
                own = block.label if block.is_object else (block.clause_num if block.kind == "heading" else "")
                for ref_kind, ref_target in find_xrefs(block.text, own):
                    located = _locate(extracted, ref_kind, ref_target)
                    if located is None:
                        continue
                    for hit in page.search_for(ref_target, clip=pymupdf.Rect(block.bbox)) or \
                            page.search_for(ref_target.upper(), clip=pymupdf.Rect(block.bbox)):
                        if not any(hit.intersects(c) for c in covered):
                            covered.append(hit)
                            report.unlinked.append(Unlinked(index + 1, tuple(hit), ref_target, located.page, _point(located)))
        # Bookmarks against the headings (ADR-032): get_toc() reports a bookmark to a missing page
        # object as page 1, so the raw check decides where each one points
        entries = []
        for level, title, page_no, detail in doc.get_toc(simple=False):
            kind, target, page_index, why = destination_of(doc, detail["xref"], page_xrefs) if detail.get("xref") else ("goto", "", None, "dead")
            entries.append((level, title, None if why == "dead" or kind not in ("goto", "named") else page_index + 1))
        matches, unnamed = match_outline(entries, [b for b in extracted.blocks if b.kind == "heading"])
        for m in matches:
            bookmark = Bookmark(m.index, m.level, m.title, m.page, OK)
            if m.heading is None:
                bookmark.state = UNCHECKED if m.page is not None else UNRESOLVED
            elif m.page is None:
                bookmark.state, bookmark.proposed_page, bookmark.proposed_point = DEAD, m.heading.page, _point(m.heading)
            elif m.page != m.heading.page:
                bookmark.state, bookmark.proposed_page, bookmark.proposed_point = WRONG, m.heading.page, _point(m.heading)
            if m.by_number:
                bookmark.proposed_title = _heading_title(m.heading)
            report.bookmarks.append(bookmark)
        report.unbookmarked = [Unbookmarked(b.page, _heading_title(b), _level_of(b.clause_num) if b.clause_num else 1) for b in unnamed]
    report.counts = {state: sum(1 for l in report.links if l.state == state) for state in STATES}
    return report


# ---- The fix --------------------------------------------------------------------------------------

def fixed(file_bytes: bytes, report: Report, skip: Set[int] = frozenset(), add: bool = False, outline: bool = False,
          extractor: Optional[PDFExtractor] = None) -> bytes:
    """
    The PDF with the report's proposed fixes applied (those not skipped), links added for unlinked
    references when asked, and with `outline` the bookmarks rebuilt from the headings (replacing them).
    """
    if report.refused:
        raise ValueError(report.refused)
    rebuilt = outline_from_headings((extractor or PDFExtractor(use_ocr=False)).extract(file_bytes, report.filename)) if outline else None
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    with doc:
        by_page: Dict[int, List[Link]] = {}
        for link in report.links:
            if link.proposed_page is not None and link.id not in skip:
                by_page.setdefault(link.page, []).append(link)
        added: Dict[int, List[Unlinked]] = {}
        for item in report.unlinked if add else []:
            added.setdefault(item.page, []).append(item)
        for page_no in sorted(set(by_page) | set(added)):
            page = doc[page_no - 1]
            # All deletions first, then a reload, then the insertions: PyMuPDF's link list on a page
            # loses its xrefs once something has been inserted
            wanted = {link.xref for link in by_page.get(page_no, [])}
            for raw in [l for l in page.get_links() if l["xref"] in wanted]:
                page.delete_link(raw)
            page = doc.reload_page(page)
            for link in by_page.get(page_no, []):
                page.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(link.rect), "page": link.proposed_page - 1,
                                  "to": pymupdf.Point(*link.proposed_point)})
            for item in added.get(page_no, []):
                page.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(item.rect),
                                  "page": item.target_page - 1, "to": pymupdf.Point(*item.target_point)})
        if rebuilt is not None:
            doc.set_toc(rebuilt)
        elif any(b.proposed_page or b.proposed_title for b in report.bookmarks):
            toc = doc.get_toc(simple=False)
            for bookmark in report.bookmarks:
                if bookmark.id > len(toc):
                    continue
                entry = toc[bookmark.id - 1]
                if bookmark.proposed_page:
                    entry[2] = bookmark.proposed_page
                    entry[3] = {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(*bookmark.proposed_point), "zoom": 0}
                if bookmark.proposed_title:
                    entry[1] = bookmark.proposed_title
            doc.set_toc(toc)
        return doc.tobytes(garbage=1, deflate=True)


def page_image(file_bytes: bytes, page_no: int, scale: float = 1.5) -> bytes:
    """One page as a PNG, for the report's Show (the file isn't in the library, so the PDF viewer can't open it)."""
    with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
        if not 0 < page_no <= doc.page_count:
            raise ValueError("No such page.")
        return doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
