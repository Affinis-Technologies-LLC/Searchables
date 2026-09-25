"""
Session state shared across the app, and the callbacks that change it.

"selected": index of the highlighted search result; "view_doc"/"view_page": the page on screen,
which page navigation can move away from the selected result; "view_target": a region to outline
after following a cross-reference or opening a pin. Callbacks run before the script, so they work
from values saved in session state rather than the results themselves.
"""
from typing import Optional, Tuple

import streamlit as st

MAIN_TAB = "main_tab"
SEARCH_TAB, COMPARE_TAB, GLOSSARY_TAB, COLLECTIONS_TAB, LIBRARY_TAB = (
    "Search", "Compare", "Glossary", "Collections", "Library"
)


def show_page(doc_id: int, page: int, target=None, focus: Optional[int] = None) -> None:
    """Shows a page, optionally outlining `target` (a bbox) and focusing passage `focus` for the Related tab."""
    st.session_state["view_doc"] = doc_id
    st.session_state["view_page"] = page
    st.session_state["page_input"] = page
    st.session_state["view_target"] = (doc_id, page, target) if target else None
    st.session_state["focus_block"] = focus


def select_result(index: int) -> None:
    locations = st.session_state.get("result_locations", [])
    if 0 <= index < len(locations):
        doc_id, page, block_id = locations[index]
        st.session_state["selected"] = index
        st.session_state["passage_trail"] = []  # A new starting point for following related passages
        show_page(doc_id, page, focus=block_id)


def step_page(delta: int, page_count: int) -> None:
    page = min(max(st.session_state["view_page"] + delta, 1), page_count)
    show_page(st.session_state["view_doc"], page)


def jump_to_page() -> None:
    show_page(st.session_state["view_doc"], st.session_state["page_input"])


def set_query(query: str) -> None:
    """
    Runs a search from outside the search box (recent searches). The box's own widget state is
    dropped so it re-reads "query"; Streamlit also discards it whenever the Search tab isn't drawn.
    """
    st.session_state["query"] = query
    st.session_state.pop("query_input", None)
    st.session_state[MAIN_TAB] = SEARCH_TAB


# ---- Identifier trail ---------------------------------------------------------------------------
# "id_trail" records identifiers followed from the related-identifiers panel (K3.5 → FLD 2041 → …),
# so Back can retrace the path. Typing a new identifier starts a new trail.

def _search_identifier(value: str) -> None:
    set_query(value)
    st.session_state["id_mode"] = True
    st.session_state.pop("id_mode_input", None)  # Re-read by the toggle, like the search box


def follow_identifier(value: str) -> None:
    st.session_state.setdefault("id_trail", []).append(value)
    _search_identifier(value)


def replace_identifier(value: str) -> None:
    """A suggestion replaces the unmatched identifier rather than extending the trail."""
    trail = st.session_state.setdefault("id_trail", [])
    trail[-1:] = [value]
    _search_identifier(value)


def trail_back() -> None:
    trail = st.session_state.get("id_trail", [])
    if len(trail) > 1:
        trail.pop()
        _search_identifier(trail[-1])


# ---- Passage trail (Related tab) ----------------------------------------------------------------
# "passage_trail" entries are (doc_id, page, bbox, block_id, label): the passages visited by
# following related passages, so Back can retrace the path.
PassageStop = Tuple[int, int, Optional[tuple], int, str]


def focus_passage(doc_id: int, page: int, bboxes: dict, picker_key: str) -> None:
    """The Related tab's passage picker: focus and outline the chosen passage."""
    block_id = st.session_state.get(picker_key)
    show_page(doc_id, page, bboxes.get(block_id), focus=block_id)


def follow_passage(target: PassageStop, origin: PassageStop) -> None:
    trail = st.session_state.setdefault("passage_trail", [])
    if not trail:
        trail.append(origin)
    trail.append(target)
    doc_id, page, bbox, block_id, _ = target
    show_page(doc_id, page, bbox, focus=block_id)


def passage_back() -> None:
    trail = st.session_state.get("passage_trail", [])
    if len(trail) > 1:
        trail.pop()
        doc_id, page, bbox, block_id, _ = trail[-1]
        show_page(doc_id, page, bbox, focus=block_id)
