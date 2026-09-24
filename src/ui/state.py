"""
Session state shared across the app, and the callbacks that change it.

"selected": index of the highlighted search result; "view_doc"/"view_page": the page on screen,
which page navigation can move away from the selected result; "view_target": a region to outline
after following a cross-reference or opening a pin. Callbacks run before the script, so they work
from values saved in session state rather than the results themselves.
"""
import streamlit as st

MAIN_TAB = "main_tab"
SEARCH_TAB, COMPARE_TAB, GLOSSARY_TAB, COLLECTIONS_TAB, LIBRARY_TAB = (
    "Search", "Compare", "Glossary", "Collections", "Library"
)


def show_page(doc_id: int, page: int, target=None) -> None:
    st.session_state["view_doc"] = doc_id
    st.session_state["view_page"] = page
    st.session_state["page_input"] = page
    st.session_state["view_target"] = (doc_id, page, target) if target else None


def select_result(index: int) -> None:
    locations = st.session_state.get("result_locations", [])
    if 0 <= index < len(locations):
        st.session_state["selected"] = index
        show_page(*locations[index])


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
