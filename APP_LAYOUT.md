pdf_query_engine/
├── .streamlit/
│   └── config.toml             # Streamlit theme & server options
├── app.py                      # Main entrypoint: page setup, sidebar, Search tab, wiring
├── requirements.txt
├── data/                       # Library: stored PDFs + SQLite index & collections (git-ignored)
├── src/
│   ├── __init__.py
│   ├── config.py               # Constants, thresholds, and paths
│   ├── models.py               # Typed dataclasses (TextBlock, Document, SearchResult, Pin, …)
│   ├── extractor/
│   │   ├── __init__.py
│   │   ├── pdf.py              # PyMuPDF ingestion, OCR & block extraction
│   │   ├── objects.py          # Tables, figures (via captions) & cross-reference detection
│   │   ├── provisions.py       # shall / should / may / NOTE classification
│   │   └── structure.py        # Clause headings & running header/footer detection
│   ├── search/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base retriever interface
│   │   ├── bm25.py             # In-memory BM25 (superseded by library.py; kept for hybrid.py)
│   │   ├── library.py          # Persistent library: documents, blocks, tables, xrefs, history, FTS5 search
│   │   ├── query.py            # User query → safe FTS5 query (phrases, OR, NOT, prefix)
│   │   └── hybrid.py           # (Extensible) Dense/RRF engine
│   ├── research/
│   │   ├── __init__.py
│   │   ├── collections.py      # Collections of pins (self-contained copies of passages/tables)
│   │   └── export.py           # Collection → Markdown / Word with citations
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── state.py            # Session state & navigation callbacks
│   │   ├── viewer.py           # Page viewer: page image, text, tables & figures, references
│   │   ├── pins.py             # Pin buttons
│   │   ├── tables.py           # Table → DataFrame / HTML / pin payload
│   │   ├── collections_tab.py  # Collections tab
│   │   └── library_tab.py      # Library tab
│   ├── viewer/
│   │   ├── __init__.py
│   │   └── render.py           # Page images with search hits highlighted; figure crops
│   └── utils/
│       ├── __init__.py
│       └── formatting.py       # Highlighting, HTML sanitization, export
