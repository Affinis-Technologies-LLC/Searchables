pdf_query_engine/
├── .streamlit/
│   └── config.toml             # Streamlit theme & server options
├── app.py                      # Main entrypoint: sign-in gate, page setup, sidebar, Search tab, wiring
├── README.md                   # Overview, setup, meaning-search model, data and configuration
├── requirements.txt
├── data/                       # Library: stored PDFs, SQLite index, collections, password hash (git-ignored)
├── models/                     # Downloaded meaning-search model (git-ignored)
├── deploy/
│   ├── macos/
│   │   ├── run.sh                  # Run in a terminal (sets up .venv on first use)
│   │   ├── install-service.sh      # Background service (launchd LaunchAgent): starts at login
│   │   ├── uninstall-service.sh    # Removes the service; keeps the library
│   │   ├── common.sh               # Shared helpers: Python 3.10+ lookup, .venv, Tesseract
│   │   └── README.md               # macOS setup, security and troubleshooting
│   └── windows/
│       ├── run.ps1                 # Run in a PowerShell window (sets up .venv on first use)
│       ├── install-service.ps1     # Installs/updates the Windows service (WinSW), venv, data folder
│       ├── uninstall-service.ps1   # Removes the service; keeps the library unless -RemoveData
│       └── README.md               # Windows setup, service, security and troubleshooting
├── src/
│   ├── __init__.py
│   ├── config.py               # Constants, thresholds, and paths
│   ├── models.py               # Typed dataclasses (TextBlock, Document, SearchResult, Pin, …)
│   ├── extractor/
│   │   ├── __init__.py
│   │   ├── pdf.py              # PyMuPDF ingestion, OCR & block extraction
│   │   ├── identifiers.py      # Identifier discovery: candidates, families by shape, roles
│   │   ├── objects.py          # Tables, figures (via captions) & cross-reference detection
│   │   ├── provisions.py       # shall / should / may / NOTE classification
│   │   └── structure.py        # Clause headings & running header/footer detection
│   ├── search/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base retriever interface
│   │   ├── bm25.py             # In-memory BM25 (superseded by library.py; kept for hybrid.py)
│   │   ├── indexer.py          # Background indexing queue (add, re-index, add meaning search)
│   │   ├── library.py          # Persistent library: documents, blocks, tables, xrefs, history, keyword + meaning search, related passages
│   │   ├── semantic.py         # Local embedding model (Microsoft E5): passage/query vectors, sentence matching
│   │   ├── query.py            # User query → safe FTS5 query (phrases, OR, NOT, prefix)
│   │   └── hybrid.py           # (Extensible) Dense/RRF engine
│   ├── research/
│   │   ├── __init__.py
│   │   ├── assess.py           # Same-topic assessment rules: values, shall/should/may, negation, identifiers
│   │   ├── collections.py      # Collections of pins (self-contained copies of passages/tables)
│   │   ├── compare.py          # Edition comparison: clause pairing, word diffs, provision changes
│   │   ├── export.py           # Collection → Markdown / Word with citations
│   │   └── glossary.py         # Defined terms from "Terms and definitions" clauses
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── auth.py             # Password sign-in, lockout, idle time-out, account menu
│   │   ├── related_panel.py    # Results | Related switch and the Related view
│   │   ├── state.py            # Session state & navigation callbacks
│   │   ├── viewer.py           # Page viewer: page image, text, tables & figures, references
│   │   ├── pins.py             # Pin buttons
│   │   ├── tables.py           # Table → DataFrame / HTML / pin payload
│   │   ├── terms.py            # Cached glossaries and comparisons
│   │   ├── collections_tab.py  # Collections tab
│   │   ├── compare_tab.py      # Compare tab
│   │   ├── glossary_tab.py     # Glossary tab
│   │   └── library_tab.py      # Library tab
│   ├── viewer/
│   │   ├── __init__.py
│   │   └── render.py           # Page images with search hits highlighted; figure crops
│   └── utils/
│       ├── __init__.py
│       └── formatting.py       # Highlighting, HTML sanitization, export
