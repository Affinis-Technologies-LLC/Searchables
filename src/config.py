import os
from pathlib import Path

# Storage — the library lives next to the app, outside version control.
# SEARCHABLES_DATA_DIR points it elsewhere (e.g. a throwaway library for testing).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SEARCHABLES_DATA_DIR", PROJECT_ROOT / "data"))
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "library.db"

# Block extraction
MIN_BLOCK_CHARS = 15            # Shorter blocks are layout noise (page numbers, stray labels)
MAX_HEADING_CHARS = 120         # Longer lines are body text, never clause headings

# Bump when extraction gains features; documents indexed by an older version can be re-indexed
EXTRACTOR_VERSION = 2           # 2: tables, figures, cross-references

# Tables and figures
CAPTION_MAX_GAP = 40            # Points between a table and its caption
FIGURE_BODY_TEXT_CHARS = 80     # Text blocks this long are body paragraphs, which bound a figure's top
TABLE_OVERLAP_FRACTION = 0.7    # Text blocks this much inside a table are cells, not passages

# Running headers/footers: text in the top/bottom margin repeated on most pages
MARGIN_FRACTION = 0.08          # Fraction of page height treated as header/footer band
REPEAT_FRACTION = 0.5           # Present on at least this share of pages → stripped
MIN_PAGES_FOR_REPEAT = 3        # Too few pages to tell a running header from content

# OCR for scanned pages (requires Tesseract)
OCR_MIN_CHARS = 20              # Pages with less extractable text than this get OCR'd
OCR_DPI = 300
OCR_LANGUAGE = "eng"

# Search
DEFAULT_MAX_RESULTS = 25
HEADING_SCORE_WEIGHT = 0.5      # BM25 favours very short text; keeps bare headings below body passages
MAX_DOCUMENT_ORDER_RESULTS = 500

# Page viewer
RESULTS_PANE_HEIGHT = 900       # Pixels; the results list scrolls inside this so the page stays in view
VIEWER_OCR_DPI = 200            # Lower than ingest OCR: only needs word positions for highlighting, not accuracy
VIEWER_ZOOM_LEVELS = [1.0, 1.5, 2.0, 3.0]  # Display width relative to the pane; 1.0 = fit width
VIEWER_RENDER_SCALE = 2.0       # Pixels per PDF point at fit width: sharp on high-DPI screens
VIEWER_MAX_RENDER_SCALE = 5.0   # Caps image size at high zoom

# Research workflow
RECENT_SEARCHES = 12            # Shown in the sidebar
