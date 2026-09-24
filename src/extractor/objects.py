"""Finds tables, figures and cross-references on standard pages."""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pymupdf

from src import config
from src.models import BBox

# "Table 5 — Limits", "Table A.1: Limits", "Table 5 (continued)". A separator (or nothing after the
# number) is required so body sentences like "Table 5 gives the limits…" aren't taken as captions.
# Any punctuation counts as the separator: PDFs encode the dash variously (—, –, ·, or "?" when the
# font lacks the glyph).
_CAPTION = r"^{word}\s+(?P<num>(?:[A-Z]\.)?\d+(?:\.\d+)*)\s*(?P<cont>\(continued\))?\s*(?:[^\w\s(]\s*(?P<title>.*))?$"
TABLE_CAPTION = re.compile(_CAPTION.format(word="Table"))
FIGURE_CAPTION = re.compile(_CAPTION.format(word="Figure"))

_NUM = r"(?:[A-Z]\.)?\d+(?:\.\d+)*"
_LIST_SEP = r"\s*(?:,|and|or|to)\s*"
_TABLE_REF = re.compile(rf"\bTables?\s+({_NUM}(?:{_LIST_SEP}{_NUM})*)")
_FIGURE_REF = re.compile(rf"\bFigures?\s+({_NUM}(?:{_LIST_SEP}{_NUM})*)")
_ANNEX_REF = re.compile(rf"\bAnnex(?:es)?\s+([A-Z]\b(?:{_LIST_SEP}[A-Z]\b)*)")
# Bare dotted numbers are common in body text ("1.5 times"), so a clause reference needs a lead-in
# word; resolution later also requires the clause to exist in the document.
# (?!\.?\d) ends the number without rejecting a sentence-final full stop ("see 4.2.")
_CLAUSE_WORD_REF = re.compile(r"\b(?:[Ss]ub)?[Cc]lauses?\s+(\d{1,2}(?:\.\d{1,3}){0,5})(?!\.?\d)")
_CLAUSE_LEADIN_REF = re.compile(
    r"\b(?:see|in|of|to|under|per|with|from|and|according to|specified in|given in)\s+(\d{1,2}(?:\.\d{1,3}){1,5})(?!\.?\d)"
)
_STANDARD_REF = re.compile(
    r"\b(?:ISO|IEC|EN|ASTM|ASME|API|BS|DIN|IEEE|NFPA|ANSI|CSA|UL)(?:[ /](?:IEC|EN|ISO|TS|TR|PAS))*"
    r"\s?(?:[A-Z]{1,2}\s?)?\d+(?:[-.]\d+)*(?::\d{4})?"
)


@dataclass
class PageTable:
    bbox: BBox
    columns: List[str]
    rows: List[List[str]]
    caption_index: Optional[int] = None   # Index into the page's blocks of the "Table N —" caption


@dataclass
class PageFigure:
    caption_index: int
    bbox: BBox                            # Graphic region plus caption


@dataclass
class Caption:
    label: str                            # "Table 1"
    title: str
    continued: bool = False


def parse_caption(text: str) -> Optional[Caption]:
    text = " ".join(text.split())
    for pattern, word in ((TABLE_CAPTION, "Table"), (FIGURE_CAPTION, "Figure")):
        match = pattern.match(text)
        if match and len(text) <= config.MAX_HEADING_CHARS * 2:
            return Caption(f"{word} {match.group('num')}", (match.group("title") or "").strip(), bool(match.group("cont")))
    return None


def _clean_cell(cell: Optional[str]) -> str:
    return " ".join((cell or "").split())


def _ruled_region(page: pymupdf.Page) -> Optional[pymupdf.Rect]:
    """
    The area covered by horizontal and vertical rules, or None when the page can't hold a ruled
    table. PyMuPDF's line-based table finder needs both kinds of rule to form cells, so pages
    without them (most pages) can skip it: it's by far the slowest step of indexing.
    """
    height = page.rect.height
    band = height * config.MARGIN_FRACTION
    horizontal = vertical = 0
    # Bounds are tracked by hand: Rect's "|" skips zero-area rects, and a rule is exactly that
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for path in page.get_cdrawings():
        for item in path["items"]:
            if item[0] == "l":
                (ax, ay), (bx, by) = item[1], item[2]
                rect = pymupdf.Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            elif item[0] == "re":
                rect = pymupdf.Rect(item[1])
            else:
                continue  # Curves and quads don't form table grids
            if rect.y1 <= band or rect.y0 >= height - band:
                continue  # Header/footer rules
            wide, tall = rect.width >= config.TABLE_MIN_RULE, rect.height >= config.TABLE_MIN_RULE
            if not (wide or tall):
                continue
            if item[0] == "re":  # A rectangle contributes both edges in each direction it spans
                horizontal += 2 if wide else 0
                vertical += 2 if tall else 0
            elif rect.height < 1:
                horizontal += 1
            elif rect.width < 1:
                vertical += 1
            else:
                continue  # Diagonal stroke: part of a drawing, not a grid
            x0, y0 = min(x0, rect.x0), min(y0, rect.y0)
            x1, y1 = max(x1, rect.x1), max(y1, rect.y1)
    return pymupdf.Rect(x0, y0, x1, y1) if horizontal >= 2 and vertical >= 2 else None


def find_tables(page: pymupdf.Page, blocks: List[tuple]) -> List[PageTable]:
    """Ruled tables on the page, each paired with its caption block when one sits just above or below."""
    region = _ruled_region(page)
    if region is None:
        return []
    try:
        # Clipping to the ruled area keeps the finder from reading every character on the page
        found = page.find_tables(clip=region + (-2, -2, 2, 2)).tables
    except Exception:
        return []  # Table detection is best-effort; a malformed page shouldn't stop ingestion

    tables = []
    for tab in found:
        grid = [[_clean_cell(c) for c in row] for row in tab.extract()]
        grid = [row for row in grid if any(row)]
        if len(grid) < 2 or tab.col_count < 2:
            continue
        # tab.header can report the caption above the table as the header; the first row is reliable
        table = PageTable(bbox=tuple(tab.bbox), columns=grid[0], rows=grid[1:])
        table.caption_index = _nearest_caption(table.bbox, blocks, "Table")
        tables.append(table)
    return tables


def _nearest_caption(bbox: BBox, blocks: List[tuple], word: str) -> Optional[int]:
    best, best_gap = None, None
    for i, b in enumerate(blocks):
        caption = parse_caption(b[4]) if b[6] == 0 else None
        if not caption or not caption.label.startswith(word):
            continue
        overlaps = b[0] < bbox[2] and b[2] > bbox[0]
        gap_above = bbox[1] - b[3]            # Caption above the table (ISO style)
        gap_below = b[1] - bbox[3]            # Caption below
        gap = gap_above if gap_above >= -2 else gap_below
        if overlaps and -2 <= gap <= config.CAPTION_MAX_GAP and (best_gap is None or gap < best_gap):
            best, best_gap = i, gap
    return best


def find_figures(page: pymupdf.Page, blocks: List[tuple], table_boxes: List[BBox]) -> List[PageFigure]:
    """
    Figures located by their "Figure N —" caption: the graphic is the drawings/images between the
    caption and the body text above it (standards put figure captions below the figure).
    """
    captions = [i for i, b in enumerate(blocks)
                if b[6] == 0 and (c := parse_caption(b[4])) and c.label.startswith("Figure")]
    if not captions:
        return []

    height = page.rect.height
    band = height * config.MARGIN_FRACTION
    graphics = [pymupdf.Rect(d["rect"]) for d in page.get_drawings()]
    for image in page.get_images():
        graphics.extend(page.get_image_rects(image[0]))
    # Header/footer rules and table grids aren't figure content
    graphics = [g for g in graphics
                if g.y0 > band and g.y1 < height - band
                and not any(pymupdf.Rect(t).contains(g) for t in table_boxes)]

    figures = []
    for index in captions:
        cap = pymupdf.Rect(blocks[index][:4])
        # The figure can't extend above the nearest paragraph of body text over the caption
        body_above = [b[3] for b in blocks
                      if b[6] == 0 and b[3] <= cap.y0 and len(b[4].strip()) >= config.FIGURE_BODY_TEXT_CHARS]
        top = max(body_above, default=band)
        region = pymupdf.Rect()
        for g in graphics:
            if g.y0 >= top - 2 and g.y1 <= cap.y0 + 2:
                region |= g
        bbox = (region | cap) if not region.is_empty else cap
        figures.append(PageFigure(caption_index=index, bbox=tuple(bbox)))
    return figures


def find_xrefs(text: str, own_label: str = "") -> List[Tuple[str, str]]:
    """(kind, target) pairs for references in text, in order of appearance, without duplicates."""
    refs: List[Tuple[int, str, str]] = []

    for pattern, kind, word in ((_TABLE_REF, "table", "Table"), (_FIGURE_REF, "figure", "Figure")):
        for match in pattern.finditer(text):
            for num in re.findall(_NUM, match.group(1)):
                refs.append((match.start(), kind, f"{word} {num}"))
    for match in _ANNEX_REF.finditer(text):
        for letter in re.findall(r"\b[A-Z]\b", match.group(1)):
            refs.append((match.start(), "annex", f"Annex {letter}"))
    for pattern in (_CLAUSE_WORD_REF, _CLAUSE_LEADIN_REF):
        for match in pattern.finditer(text):
            refs.append((match.start(1), "clause", match.group(1)))
    for match in _STANDARD_REF.finditer(text):
        refs.append((match.start(), "standard", " ".join(match.group(0).split())))

    seen, ordered = set(), []
    for _, kind, target in sorted(refs):
        if target != own_label and (kind, target) not in seen:
            seen.add((kind, target))
            ordered.append((kind, target))
    return ordered


def standard_pattern(target: str) -> re.Pattern:
    """Matches a standard designation in a title/filename, ignoring year and punctuation ("ISO_4126-1_2013")."""
    designation = target.split(":")[0]
    tokens = re.findall(r"[a-z]+|\d+", designation.lower())
    return re.compile(r"(?<![a-z0-9])" + r"\W*".join(map(re.escape, tokens)) + r"(?!\d)")
