"""Renders PDF pages as images with search hits highlighted in place."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import pymupdf

from src import config
from src.extractor.pdf import looks_scanned, ocr_available
from src.models import BBox

_HIT_COLOR = (1.0, 0.85, 0.1)       # Yellow highlighter
_TARGET_COLOR = (0.15, 0.39, 0.92)  # Matches the app's primary blue
_TARGET_PADDING = 4                 # Points between the passage and its outline
_WORD_PUNCTUATION = ".,;:!?()[]{}\"'“”‘’"  # Stripped from page words before comparing with terms


@dataclass(frozen=True)
class RenderedPage:
    png: bytes
    hit_count: int      # Highlights drawn (0 on a scanned page when OCR is unavailable)


def render_page(
    pdf_path: Path,
    page_no: int,
    terms: Sequence[str] = (),
    target: Optional[BBox] = None,
    zoom: float = 1.5,
    clip: Optional[BBox] = None,
) -> RenderedPage:
    """
    Draws a page (1-based) with every occurrence of `terms` highlighted and the target
    passage outlined; `clip` crops to a region (e.g. a figure). Annotations are added to an
    in-memory copy only; the PDF is never modified.
    """
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]

        # Scanned pages have no text layer to search, so OCR one (callers cache the rendered result)
        textpage = None
        if terms and looks_scanned(page) and ocr_available():
            try:
                textpage = page.get_textpage_ocr(language=config.OCR_LANGUAGE, dpi=config.VIEWER_OCR_DPI, full=True)
            except Exception:
                textpage = None  # Fall back to the outline alone

        # Single-word terms match whole words only: search_for() finds substrings, which would mark
        # "K3.5" inside "K3.5C1" and "calibration" inside "recalibration"
        words = page.get_text("words", textpage=textpage) if terms else []
        quads = []
        for term in terms:
            if " " in term:
                quads.extend(page.search_for(term, quads=True, textpage=textpage))
            else:
                wanted = term.lower()
                quads.extend(pymupdf.Rect(w[:4]).quad for w in words if w[4].strip(_WORD_PUNCTUATION).lower() == wanted)
        if quads:
            highlight = page.add_highlight_annot(quads)
            highlight.set_colors(stroke=_HIT_COLOR)
            highlight.update()

        if target:
            outline = page.add_rect_annot(pymupdf.Rect(target) + (-_TARGET_PADDING, -_TARGET_PADDING,
                                                                    _TARGET_PADDING, _TARGET_PADDING))
            outline.set_colors(stroke=_TARGET_COLOR)
            outline.set_border(width=1.5)
            outline.update()

        margin = _TARGET_PADDING * 2
        region = (pymupdf.Rect(clip) + (-margin, -margin, margin, margin)) & page.rect if clip else None
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True, clip=region)
        return RenderedPage(png=pixmap.tobytes("png"), hit_count=len(quads))
