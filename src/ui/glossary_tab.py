"""The Glossary tab: every defined term in the library, with the definition's page alongside."""
from typing import List

import pandas as pd
import streamlit as st

from src import config
from src.models import Document
from src.search.library import Library
from src.ui.state import show_page
from src.ui.terms import glossary
from src.ui.related_panel import left_pane
from src.ui.viewer import render_viewer


def render_glossary(library: Library, documents: List[Document]) -> None:
    titles = {d.id: d.title for d in documents}
    terms = [term for doc in documents for term in glossary(library, doc)]
    if not terms:
        st.info("No defined terms found. Terms are read from each document's “Terms and definitions” clause "
                "(numbered entries such as “3.1 set pressure”).")
        return

    text = st.text_input("Filter terms", key="glossary_filter", placeholder="Term, synonym or words in the definition")
    needle = text.strip().lower()
    shown = [t for t in terms if not needle
             or any(needle in n.lower() for n in t.names) or needle in t.definition.lower()]
    shown.sort(key=lambda t: (t.term.lower(), titles[t.doc_id]))
    st.caption(f"{len(shown)} of {len(terms)} terms across {len({t.doc_id for t in terms})} documents · "
               "select a row to open its definition")

    list_col, viewer_col = st.columns([2, 3], gap="medium")
    with list_col:
        def term_list() -> None:
            # Document sits beside the term: the same term defined in two editions must be told apart at a glance
            frame = pd.DataFrame([
                {"Term": t.term + (f" ({'; '.join(t.synonyms)})" if t.synonyms else ""), "Document": titles[t.doc_id],
                 "Clause": t.clause_num, "Definition": t.definition, "Page": t.page_label}
                for t in shown
            ])
            row_height, header_height = 35, 38
            event = st.dataframe(frame, hide_index=True, width="stretch",
                                 height=min(config.RESULTS_PANE_HEIGHT, header_height + row_height * max(len(shown), 1)),
                                 on_select="rerun", selection_mode="single-row", key="glossary_table")
            rows = event.selection.rows if event and event.selection else []
            if rows and rows[0] < len(shown):
                term = shown[rows[0]]
                # Only move the viewer when the selection changes, so page navigation isn't undone on every rerun
                if st.session_state.get("glossary_selected") != (term.doc_id, term.clause_num):
                    st.session_state["glossary_selected"] = (term.doc_id, term.clause_num)
                    show_page(term.doc_id, term.page, term.bbox)
                    st.session_state["glossary_query"] = f'"{term.term}"'
                    st.rerun()  # The Related count was computed before this selection moved the viewer

        left_pane(library, term_list)
    with viewer_col:
        with st.container(border=True):
            render_viewer(library, st.session_state.get("glossary_query", ""))
