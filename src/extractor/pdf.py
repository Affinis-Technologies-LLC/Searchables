import re
import pymupdf
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from src import config
from src.extractor.identifiers import extract_occurrences
from src.extractor.objects import PageFigure, PageTable, find_figures, find_tables, find_xrefs, parse_caption
from src.extractor.provisions import classify_provision
from src.extractor.structure import HeadingDetector, find_running_text, is_running_text
from src.models import CrossRef, ExtractedDocument, TableData, TextBlock

# Omitting TEXT_PRESERVE_LIGATURES expands ligatures ("ﬁ" → "fi") so search matches them
_TEXT_FLAGS = pymupdf.TEXT_MEDIABOX_CLIP
# "require-\nments" → "requirements". PyMuPDF's TEXT_DEHYPHENATE has no effect on "blocks" output.
# Lowercase on both sides only, so "ISO-\n9001" and "Type-\nA" keep their hyphen.
_LINE_END_HYPHEN = re.compile(r"(?<=[a-z])-\n(?=[a-z])")

ProgressCallback = Callable[[int, int], None]


def ocr_available() -> bool:
    try:
        return bool(pymupdf.get_tessdata())
    except Exception:
        return False


def looks_scanned(page: pymupdf.Page, blocks: Optional[List[tuple]] = None) -> bool:
    """A page with images but next to no text layer is a scan."""
    if blocks is None:
        blocks = page.get_text("blocks", flags=_TEXT_FLAGS)
    text_chars = sum(len(b[4].strip()) for b in blocks if b[6] == 0)
    return text_chars < config.OCR_MIN_CHARS and bool(page.get_images())


def _overlap_fraction(inner: tuple, outer: tuple) -> float:
    """Share of `inner`'s area that lies inside `outer`."""
    r = pymupdf.Rect(inner[:4])
    area = r.get_area()
    return (r & pymupdf.Rect(outer[:4])).get_area() / area if area else 0.0


@dataclass
class _PageData:
    number: int                 # 1-based
    height: float
    label: str
    blocks: List[tuple]         # (x0, y0, x1, y1, text, block_no, block_type)
    tables: List[PageTable] = field(default_factory=list)
    figures: List[PageFigure] = field(default_factory=list)


class PDFExtractor:
    def __init__(self, min_char_length: int = config.MIN_BLOCK_CHARS, use_ocr: Optional[bool] = None):
        self.min_char_length = min_char_length
        self.use_ocr = ocr_available() if use_ocr is None else use_ocr

    def extract(
        self,
        file_bytes: bytes,
        filename: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> ExtractedDocument:
        """
        Extracts text blocks from a PDF, tagged with clause, printed page label and position, plus
        tables, figures and cross-references. Scanned pages are OCR'd when Tesseract is available;
        running headers/footers are dropped.
        """
        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise ValueError(f"Failed to open PDF document: {e}") from e

        # Context manager closes the document even if extraction fails partway
        with doc:
            result = ExtractedDocument(title=Path(filename).stem, page_count=len(doc))
            pages = self._read_pages(doc, result, on_progress)
            running_keys = find_running_text((p.height, p.blocks) for p in pages)
            detector = HeadingDetector(doc.get_toc())

            for page in pages:
                self._emit_page(page, running_keys, detector, result)

        for block in result.blocks:
            # A caption or heading naming itself ("Annex A (informative) …") isn't a reference
            own = block.label if block.is_object else (block.clause_num if block.kind == "heading" else "")
            result.xrefs.extend(
                CrossRef(block_id=block.id, kind=kind, target=target)
                for kind, target in find_xrefs(block.text, own)
            )
        result.identifiers = extract_occurrences(result.blocks, result.tables)
        return result

    def _read_pages(
        self,
        doc: pymupdf.Document,
        result: ExtractedDocument,
        on_progress: Optional[ProgressCallback],
    ) -> List[_PageData]:
        pages = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_no = page_idx + 1
            blocks = page.get_text("blocks", flags=_TEXT_FLAGS, sort=True)
            data = _PageData(page_no, page.rect.height, page.get_label() or "", blocks)

            if looks_scanned(page, blocks):
                # No text layer to find tables or figure captions in; OCR text becomes plain passages
                if self.use_ocr:
                    try:
                        textpage = page.get_textpage_ocr(
                            flags=_TEXT_FLAGS, language=config.OCR_LANGUAGE, dpi=config.OCR_DPI, full=True
                        )
                        data.blocks = page.get_text("blocks", textpage=textpage, sort=True)
                        result.ocr_pages.append(page_no)
                    except Exception:
                        result.unreadable_pages.append(page_no)
                else:
                    result.unreadable_pages.append(page_no)
            else:
                data.tables = find_tables(page, blocks)
                data.figures = find_figures(page, blocks, [t.bbox for t in data.tables])

            pages.append(data)
            if on_progress:
                on_progress(page_no, len(doc))
        return pages

    def _emit_page(
        self,
        page: _PageData,
        running_keys: set,
        detector: HeadingDetector,
        result: ExtractedDocument,
    ) -> None:
        """Adds a page's blocks in reading order, with each table/figure standing in for its caption."""
        tables_by_caption = {t.caption_index: t for t in page.tables if t.caption_index is not None}
        figures_by_caption = {f.caption_index: f for f in page.figures}
        uncaptioned = [t for t in page.tables if t.caption_index is None]

        for index, b in enumerate(page.blocks):
            if b[6] != 0 or is_running_text(b, page.height, running_keys):
                continue
            # Tables without a caption go in where their top edge falls in the reading order
            while uncaptioned and uncaptioned[0].bbox[1] <= b[1]:
                self._add_table(uncaptioned.pop(0), None, page, detector, result)

            if index in tables_by_caption:
                self._add_table(tables_by_caption[index], b, page, detector, result)
            elif index in figures_by_caption:
                self._add_figure(figures_by_caption[index], b, page, detector, result)
            elif any(_overlap_fraction(b, t.bbox) >= config.TABLE_OVERLAP_FRACTION for t in page.tables):
                continue  # A table cell: indexed as part of its table, not as a passage
            else:
                block = self._to_block(b, page, detector, len(result.blocks))
                if block:
                    result.blocks.append(block)

        for table in uncaptioned:
            self._add_table(table, None, page, detector, result)

    def _add_table(self, table: PageTable, caption_block: Optional[tuple], page: _PageData,
                   detector: HeadingDetector, result: ExtractedDocument) -> None:
        caption_text = " ".join(caption_block[4].split()) if caption_block else ""
        caption = parse_caption(caption_text)
        bbox = pymupdf.Rect(table.bbox)
        if caption_block:
            bbox |= pymupdf.Rect(caption_block[:4])
        cells = " ".join(" ".join(row) for row in [table.columns, *table.rows])
        block = self._object_block("table", caption.label if caption else "", f"{caption_text} {cells}".strip(),
                                   tuple(bbox), page, detector, len(result.blocks))
        result.blocks.append(block)
        result.tables.append(TableData(block_id=block.id, columns=table.columns, rows=table.rows))

    def _add_figure(self, figure: PageFigure, caption_block: tuple, page: _PageData,
                    detector: HeadingDetector, result: ExtractedDocument) -> None:
        caption_text = " ".join(caption_block[4].split())
        caption = parse_caption(caption_text)
        result.blocks.append(self._object_block("figure", caption.label if caption else "", caption_text,
                                                figure.bbox, page, detector, len(result.blocks)))

    @staticmethod
    def _object_block(kind: str, label: str, text: str, bbox: tuple, page: _PageData,
                      detector: HeadingDetector, block_id: int) -> TextBlock:
        current = detector.current
        return TextBlock(
            id=block_id,
            page=page.number,
            text=text,
            word_count=len(text.split()),
            page_label=page.label,
            kind=kind,
            label=label,
            clause_num=current.num if current else "",
            clause_title=current.title if current else "",
            clause_path=detector.path,
            bbox=bbox,
        )

    def _to_block(
        self,
        b: tuple,
        page: _PageData,
        detector: HeadingDetector,
        block_id: int,
    ) -> Optional[TextBlock]:
        raw_text = _LINE_END_HYPHEN.sub("", b[4].strip())
        _, heading_only = detector.feed(page.number, raw_text)
        clean_text = " ".join(raw_text.split())

        # Skip single page numbers, short artifacts, or empty lines (headings are kept for navigation)
        if not heading_only and (len(clean_text) < self.min_char_length or clean_text.isdigit()):
            return None

        current = detector.current
        return TextBlock(
            id=block_id,
            page=page.number,
            text=clean_text,
            word_count=len(clean_text.split()),
            page_label=page.label,
            kind="heading" if heading_only else "text",
            clause_num=current.num if current else "",
            clause_title=current.title if current else "",
            clause_path=detector.path,
            bbox=(b[0], b[1], b[2], b[3]),
            provision="" if heading_only else classify_provision(clean_text),
        )
