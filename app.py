import html
import sqlite3
import streamlit as st
from src import config
from src.extractor.pdf import PDFExtractor
from src.research.collections import CollectionStore
from src.search.library import CONTENT_KINDS, PROVISION_FILTERS, Library
from src.search.query import SYNTAX_HELP
from src.research.glossary import terms_in_text
from src.ui.collections_tab import render_collections
from src.ui.compare_tab import render_compare
from src.ui.glossary_tab import render_glossary
from src.ui.library_tab import render_library_tab
from src.ui.pins import PinContext, pin_button
from src.ui.state import (COLLECTIONS_TAB, COMPARE_TAB, GLOSSARY_TAB, LIBRARY_TAB, MAIN_TAB, SEARCH_TAB,
                          select_result, set_query, show_page)
from src.ui.terms import glossary
from src.ui.viewer import render_viewer
from src.utils.formatting import results_to_dataframe

# Page Configuration
st.set_page_config(
    page_title="Standards Search",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inline Layout Styles
st.markdown("""
<style>
    .query-hit {
        background-color: #FEF08A;
        color: #854D0E;
        padding: 0 1px;
        border-radius: 3px;
        font-weight: 500;
    }
    .badge {
        font-size: 0.8rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 4px;
        margin-right: 6px;
        white-space: nowrap;
    }
    .badge-page { background: #2563EB; color: #FFFFFF; }
    .badge-metric { background: rgba(128, 128, 128, 0.15); color: inherit; }
    .badge-object { background: #0F766E; color: #FFFFFF; }
    .badge-requirement { background: #B91C1C; color: #FFFFFF; }
    .badge-recommendation { background: #B45309; color: #FFFFFF; }
    .badge-permission { background: #4B5563; color: #FFFFFF; }
    .badge-note { background: rgba(128, 128, 128, 0.15); color: inherit; font-style: italic; }
    .result-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; margin-bottom: 2px; }
    .result-doc { font-weight: 600; }
    .result-path { font-size: 0.85rem; opacity: 0.7; margin-bottom: 8px; }
    .result-body { line-height: 1.6; }
    .pin-quote { border-left: 3px solid rgba(128, 128, 128, 0.4); padding-left: 8px; }
    .context-block { font-size: 0.875rem; opacity: 0.6; margin: 0 0 8px; }
    .context-heading { font-weight: 600; opacity: 0.8; }
    .context-hit { opacity: 1; }
    .context-target { font-size: 0.95rem; opacity: 1; border-left: 3px solid #2563EB; padding-left: 8px; }
    .context-caption { font-weight: 600; margin-bottom: 4px; }
    .viewer-count { font-size: 0.85rem; opacity: 0.7; margin-left: auto; }
    .page-frame {
        max-height: 1000px;
        overflow: auto;
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        background: #FFFFFF;
    }
    .page-frame img { display: block; }
    .page-table { border-collapse: collapse; font-size: 0.85rem; margin-bottom: 4px; }
    .page-table th, .page-table td { border: 1px solid rgba(128, 128, 128, 0.35); padding: 3px 8px; text-align: left; }
    .page-table th { background: rgba(128, 128, 128, 0.1); }
    .diff-del { background: #FEE2E2; color: #991B1B; }
    .diff-ins { background: #DCFCE7; color: #166534; text-decoration: none; }
    .badge-diff-changed { background: #B45309; color: #FFFFFF; }
    .badge-diff-added { background: #15803D; color: #FFFFFF; }
    .badge-diff-removed { background: #B91C1C; color: #FFFFFF; }
    .badge-diff-unchanged { background: rgba(128, 128, 128, 0.15); color: inherit; }
</style>
""", unsafe_allow_html=True)

_PROVISION_BADGES = {"requirement": "shall", "recommendation": "should", "permission": "may", "note": "note"}


# Application Dependencies
@st.cache_resource
def get_library() -> Library:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Library()


@st.cache_resource
def get_collections() -> CollectionStore:
    return CollectionStore(get_library().conn)


library = get_library()
store = get_collections()
extractor = PDFExtractor()
documents = library.list_documents()

# A link (?q=…&doc=…&page=…) restores a search and the page being viewed, once per browser session
if "session_started" not in st.session_state:
    st.session_state["session_started"] = True
    st.session_state["query"] = st.query_params.get("q", "")
    try:
        st.session_state["pending_view"] = (int(st.query_params["doc"]), int(st.query_params["page"]))
    except (KeyError, ValueError):
        pass


def _pick_recent() -> None:
    picked = st.session_state.get("recent_pick")
    if picked:
        set_query(picked)
    st.session_state["recent_pick"] = None


def _create_collection() -> None:
    try:
        st.session_state["active_collection"] = store.create(st.session_state.get("new_collection_name", ""))
        st.session_state["new_collection_name"] = ""
    except ValueError as e:
        st.session_state["collection_error"] = str(e)


# Sidebar Controls
with st.sidebar:
    st.header("Search Scope")
    selected_docs = st.multiselect(
        "Documents",
        options=documents,
        format_func=lambda d: d.title,
        placeholder="All documents",
    )
    document_order = st.radio(
        "Order results by", ["Relevance", "Position in document"], horizontal=True
    ) == "Position in document"
    content = st.pills("Content", list(CONTENT_KINDS), selection_mode="multi", default=list(CONTENT_KINDS))
    # Nothing selected reads as "no filter" rather than an empty result list
    kinds = [kind for name in (content or CONTENT_KINDS) for kind in CONTENT_KINDS[name]]
    provision_names = st.pills("Provisions", list(PROVISION_FILTERS), selection_mode="multi",
                               help="Classified by verbal form: shall, should, may; NOTE/EXAMPLE are informative")
    provisions = [PROVISION_FILTERS[name] for name in provision_names]
    max_results = st.slider("Max Results", min_value=5, max_value=100, value=config.DEFAULT_MAX_RESULTS, step=5)

    st.header("Collections")
    store.ensure_default()
    collections = store.list_collections()
    active_id = st.session_state.get("active_collection")
    active = next((c for c in collections if c.id == active_id), collections[0])
    active = st.selectbox(
        "Pin to", collections, index=collections.index(active),
        format_func=lambda c: f"{c.name} ({c.pin_count})",
    )
    st.session_state["active_collection"] = active.id
    with st.popover("New collection", icon=":material/add:", width="stretch"):
        st.text_input("Name", key="new_collection_name", placeholder="e.g. Pressure relief sizing")
        st.button("Create", on_click=_create_collection, type="primary")
        if error := st.session_state.pop("collection_error", None):
            st.error(error)

    recent = library.recent_searches()
    if recent:
        st.header("Recent searches")
        st.pills("Recent searches", recent, key="recent_pick", on_change=_pick_recent, label_visibility="collapsed")

# Main Dashboard
st.title("Standards Search")
st.caption(
    f"{len(documents)} document{'s' if len(documents) != 1 else ''} in the library · "
    "keyword search with stemming, phrases and boolean operators"
)

# Only the open tab is drawn: faster, and the page viewer (used by two tabs) never appears twice
search_tab, compare_tab, glossary_tab, collections_tab, library_tab = st.tabs(
    [SEARCH_TAB, COMPARE_TAB, GLOSSARY_TAB, COLLECTIONS_TAB, LIBRARY_TAB], key=MAIN_TAB, on_change="rerun"
)
documents_by_id = {d.id: d for d in documents}


def render_result(res, index: int, selected: bool, pin_ctx: PinContext) -> None:
    block = res.block
    badges = []
    if block.is_object:
        badges.append(f'<span class="badge badge-object">{html.escape(block.label or "Untitled " + block.kind)}</span>')
    if block.clause_num:
        badges.append(f'<span class="badge badge-metric">{html.escape(block.clause_num)}</span>')
    if block.provision:
        badges.append(f'<span class="badge badge-{block.provision}">{_PROVISION_BADGES[block.provision]}</span>')
    path = html.escape(block.clause_path) if block.clause_path else "No clause detected"

    with st.container(border=True):
        # st.html skips markdown parsing, so "$" and "*" in PDF text render literally
        st.html(
            f'<div class="result-head"><span class="badge badge-page">p. {html.escape(block.display_page)}</span>'
            f'{"".join(badges)}<span class="result-doc">{html.escape(res.doc_title)}</span></div>'
            f'<div class="result-path">{path}</div>'
            f'<div class="result-body">{res.highlighted_text}</div>'
        )
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f"Score {res.score:.2f} · {res.citation}", width="stretch")
            doc = documents_by_id.get(block.doc_id)
            used = terms_in_text(glossary(library, doc), block.text) if doc and block.kind == "text" else []
            if used:
                with st.popover(f"Definitions ({len(used)})", width="content"):
                    for term in used:
                        st.html(f"<p><strong>{html.escape(term.term)}</strong> · {html.escape(term.clause_num)}<br>"
                                f"{html.escape(term.definition)}</p>")
            pin_button(pin_ctx, block, res.doc_title, res.citation, key=f"pin_{index}")
            st.button(
                "Viewing" if selected else "View page",
                key=f"view_{index}",
                type="primary" if selected else "secondary",
                disabled=selected,
                on_click=select_result,
                args=(index,),
                width="content",
            )


def run_search(query: str):
    """Returns (results, total), or None after showing the error."""
    try:
        outcome = library.search(
            query,
            doc_ids=[d.id for d in selected_docs],
            limit=config.MAX_DOCUMENT_ORDER_RESULTS if document_order else max_results,
            document_order=document_order,
            kinds=kinds,
            provisions=provisions,
        )
    except ValueError as e:
        st.warning(str(e))
        return None
    except sqlite3.OperationalError as e:
        st.error(f"Couldn't run that search: {e}")
        return None
    if st.session_state.get("last_recorded") != query:
        library.record_search(query)
        st.session_state["last_recorded"] = query
    return outcome


def sync_link(query: str) -> None:
    """Keeps the address bar pointing at this search and page, so it can be bookmarked or shared."""
    if not query.strip():
        st.query_params.clear()
        return
    params = {"q": query}
    if st.session_state.get("view_doc") is not None:
        params |= {"doc": str(st.session_state["view_doc"]), "page": str(st.session_state["view_page"])}
    st.query_params.from_dict(params)


def open_pending_view() -> None:
    """Shows the page named in the link this session was opened with, if it still exists."""
    pending = st.session_state.pop("pending_view", None)
    if pending:
        doc = library.get_document(pending[0])
        if doc and 1 <= pending[1] <= doc.page_count:
            show_page(*pending)


if search_tab.open:
    with search_tab:
        if not documents:
            st.info("The library is empty. Add standards in the **Library** tab to start searching.")
        else:
            query_col, help_col = st.columns([6, 1], vertical_alignment="bottom")
            # The box's widget state is discarded while another tab is open, so "query" is the source of truth
            query = query_col.text_input(
                "Search the library",
                value=st.session_state.get("query", ""),
                key="query_input",
                placeholder='e.g. "shall not exceed" calibration -software',
            )
            st.session_state["query"] = query
            with help_col.popover("Syntax", width="stretch"):
                st.markdown(SYNTAX_HELP)

            pin_ctx = PinContext(library, store, active.id, query, store.pinned_keys(active.id))
            outcome = run_search(query) if query.strip() else None
            if outcome is not None:
                results, total = outcome
                if not results:
                    st.warning("No passages match. Try fewer words, a prefix like `calib*`, OR between "
                               "alternatives, or fewer filters.")
                else:
                    # A new search (or scope/order change) starts the viewer on the first result
                    search_key = (query, tuple(d.id for d in selected_docs), document_order, max_results,
                                  tuple(kinds), tuple(provisions))
                    st.session_state["result_locations"] = [(r.block.doc_id, r.block.page) for r in results]
                    if (
                        st.session_state.get("search_key") != search_key
                        or st.session_state.get("selected", 0) >= len(results)  # Library changed under the same search
                    ):
                        st.session_state["search_key"] = search_key
                        select_result(0)
                        open_pending_view()
                    selected_index = st.session_state["selected"]

                    results_col, viewer_col = st.columns([2, 3], gap="medium")
                    with results_col:
                        with st.container(horizontal=True, vertical_alignment="center"):
                            st.caption(f"Showing **{len(results)}** of **{total}** matching passages", width="stretch")
                            st.button("▲ Prev", key="result_prev", disabled=selected_index == 0,
                                      on_click=select_result, args=(selected_index - 1,),
                                      shortcut="Alt+Up", help="Previous result")
                            st.button("Next ▼", key="result_next", disabled=selected_index >= len(results) - 1,
                                      on_click=select_result, args=(selected_index + 1,),
                                      shortcut="Alt+Down", help="Next result")

                        # Fixed-height pane scrolls on its own, so the page viewer stays in view
                        with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
                            for i, res in enumerate(results):
                                render_result(res, i, i == selected_index, pin_ctx)

                        st.download_button(
                            label="Download Results (CSV)",
                            data=results_to_dataframe(results).to_csv(index=False),
                            file_name="search_results.csv",
                            mime="text/csv",
                        )

                    with viewer_col:
                        with st.container(border=True):
                            render_viewer(library, query, results[selected_index].block, pin_ctx)
            sync_link(query)

if compare_tab.open:
    with compare_tab:
        render_compare(library, documents)

if glossary_tab.open:
    with glossary_tab:
        render_glossary(library, documents)

if collections_tab.open:
    with collections_tab:
        pin_ctx = PinContext(library, store, active.id, "", store.pinned_keys(active.id))
        render_collections(library, store, active, pin_ctx)

if library_tab.open:
    with library_tab:
        render_library_tab(library, extractor, documents)
