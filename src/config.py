import os
from pathlib import Path

# Storage — the library lives next to the app, outside version control.
# SEARCHABLES_DATA_DIR points it elsewhere (e.g. a throwaway library for testing).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SEARCHABLES_DATA_DIR", PROJECT_ROOT / "data"))
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "library.db"
AUTH_FILE = DATA_DIR / "auth.json"  # Password hash; delete it to set a new password


def make_private(folder: Path) -> None:
    """
    Creates a folder that only this account can open, so other accounts on the machine can't read the
    stored PDFs past the app's password. No effect on Windows, where the install script sets the
    folder's permissions instead.
    """
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass


# Meaning-based search: a local embedding model, downloaded once into MODEL_DIR (git-ignored) and
# pinned to an exact revision. Microsoft E5 (MIT licence). Changing the model re-embeds the library.
MODEL_DIR = Path(os.environ.get("SEARCHABLES_MODEL_DIR", PROJECT_ROOT / "models"))
EMBEDDING_MODEL = "intfloat/e5-base-v2"
EMBEDDING_REVISION = "f52bf8ec8c7124536f0efb74aca902b2995e5bcd"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_ID = f"{EMBEDDING_MODEL}@{EMBEDDING_REVISION[:12]}"  # Stored per document to spot stale vectors
EMBEDDING_DEVICE = "cpu"
EMBEDDING_BATCH = 8               # Passages read per step while indexing; a search waits at most one step for the model
EMBEDDING_COMMIT = 128            # Vectors are saved this often, so interrupted indexing resumes from here
EMBEDDING_MAX_CHARS = 2000        # Longer passages are cut; the model reads ~512 tokens anyway
EMBEDDING_TABLE_CHARS = 1200      # Longer tables also get a vector per run of rows this long (with caption and header)

# Sign-in
MIN_PASSWORD_LENGTH = 10
LOGIN_MAX_ATTEMPTS = 5          # Wrong passwords before sign-in is locked…
LOGIN_LOCKOUT_SECONDS = 30      # …for this long
SESSION_IDLE_MINUTES = 60       # Signed out after this long without using the app

# Block extraction
MIN_BLOCK_CHARS = 15            # Shorter blocks are layout noise (page numbers, stray labels)
MAX_HEADING_CHARS = 120         # Longer lines are body text, never clause headings
MAX_RUN_IN_TITLE_WORDS = 8      # "4.2.1 Transmit rules. The system…": longer "titles" are sentences

# Bump when extraction gains features; documents indexed by an older version can be re-indexed
EXTRACTOR_VERSION = 5           # 2: tables, figures, cross-references; 3: MIL-style conventions, identifiers;
                                # 4: identifiers written with look-alike dots and dashes; 5: deeper clause
                                # numbers, appendix sections numbered in tens, list items under "shall:"

# Identifier discovery: a family (shape such as "K#.#") counts as identifiers when it has at least
# this many distinct values, appearing in at least this many passages. Adjustable per document in
# the Library tab.
IDENTIFIER_MIN_DISTINCT = 3
IDENTIFIER_MIN_PASSAGES = 5
IDENTIFIER_EXAMPLES = 4         # Example values shown per family
IDENTIFIER_SUGGESTIONS = 12     # Offered when a searched identifier isn't found
RELATED_IDENTIFIERS = 15        # Related identifiers listed for a searched identifier
SAME_ROW_WEIGHT = 3             # Sharing a table row counts this many times more than sharing a passage

# Related passages (viewer's Related tab)
RELATED_PER_GROUP = 6           # Passages listed per group (references, shared identifiers, similar wording…)
SIMILAR_QUERY_WORDS = 16        # Distinctive words taken from a passage to find similar ones
SIMILAR_MIN_SHARED_WORDS = 2    # Fewer shared words than this isn't "similar"
SAME_TOPIC_MIN_SIMILARITY = 0.85  # Meaning similarity for two passages to count as the same topic
SAME_TOPIC_SENTENCE_SIMILARITY = 0.86  # …and at least one pair of their sentences must correspond this closely
SAME_CONTENT_SIMILARITY = 0.97    # Every sentence this close, with no difference found: "same content"
MIN_SENTENCE_WORDS = 6            # Shorter sentences ("RQ-0003 applies.") aren't used for pairing

# Tables and figures
CAPTION_MAX_GAP = 40            # Points between a table and its caption
FIGURE_BODY_TEXT_CHARS = 80     # Text blocks this long are body paragraphs, which bound a figure's top
TABLE_OVERLAP_FRACTION = 0.7    # Text blocks this much inside a table are cells, not passages
TABLE_MIN_RULE = 10             # Points; shorter strokes (ticks, underlines) aren't table rules

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
PARTIAL_MATCH_BELOW = 10        # Plain-word searches with fewer passages containing every word than this also
                                # list passages containing some of them (a question rarely matches word for word)
HEADING_SCORE_WEIGHT = 0.5      # BM25 favours very short text; keeps bare headings below body passages
MAX_DOCUMENT_ORDER_RESULTS = 500
# Meaning in search: keyword and meaning matches are merged by reciprocal rank fusion
FUSION_DEPTH = 100              # Candidates taken from each method before merging
RRF_K = 60                      # Standard fusion constant: higher flattens the difference between ranks
MEANING_MIN_SIMILARITY = 0.78   # Meaning matches below this similarity are dropped…
MEANING_BAND = 0.05             # …and so are those more than this below the best match
MEANING_TABLE_PREVIEW_CHARS = 300

# Page viewer
RESULTS_PANE_HEIGHT = 900       # Pixels; the results list scrolls inside this so the page stays in view
VIEWER_OCR_DPI = 200            # Lower than ingest OCR: only needs word positions for highlighting, not accuracy
VIEWER_ZOOM_LEVELS = [1.0, 1.5, 2.0, 3.0]  # Display width relative to the pane; 1.0 = fit width
VIEWER_RENDER_SCALE = 2.0       # Pixels per PDF point at fit width: sharp on high-DPI screens
VIEWER_MAX_RENDER_SCALE = 5.0   # Caps image size at high zoom

# Source code (the Code view)
CODE_SKIP_FOLDERS = {           # Build output and downloaded dependencies: not the project's own source
    "node_modules", "bower_components", "target", "build", "dist", "out", "coverage", "__pycache__", "venv",
}                               # Folders starting with "." (.git, .gradle, .idea…) are always skipped
CODE_MAX_FILE_BYTES = 1_000_000 # Larger source files are generated or bundled, and are skipped
CODE_MAX_RESULTS = 300          # Symbols, lines or usages listed at once
CODE_CALL_DEPTH = 4             # Levels followed in caller and callee trees
CODE_CALL_WIDTH = 30            # Callers or callees listed per step of a tree
CODE_CONTEXT_LINES = 40         # Lines shown either side of the line being looked at

# Research workflow
RECENT_SEARCHES = 12            # Shown in the sidebar
