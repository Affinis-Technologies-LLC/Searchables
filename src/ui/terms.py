"""Cached per-document glossaries and edition comparisons, shared by several views."""
from typing import List

import streamlit as st

from src.models import ClauseDiff, Document, Term
from src.research.compare import compare
from src.research.glossary import build_glossary
from src.search.library import Library


def _stamp(doc: Document) -> tuple:
    # Changes whenever a document is re-indexed with different results, invalidating the cache
    return doc.id, doc.block_count, doc.page_count, doc.extract_version


@st.cache_data(max_entries=100, show_spinner=False)
def _glossary(_library: Library, stamp: tuple) -> List[Term]:
    return build_glossary(_library.document_blocks(stamp[0]))


def glossary(library: Library, doc: Document) -> List[Term]:
    return _glossary(library, _stamp(doc))


@st.cache_data(max_entries=20, show_spinner="Comparing editions…")
def _comparison(_library: Library, old_stamp: tuple, new_stamp: tuple) -> List[ClauseDiff]:
    return compare(_library.document_blocks(old_stamp[0]), _library.document_blocks(new_stamp[0]))


def comparison(library: Library, old: Document, new: Document) -> List[ClauseDiff]:
    return _comparison(library, _stamp(old), _stamp(new))
