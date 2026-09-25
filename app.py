import html
import sqlite3
import threading
from typing import List, Optional, Tuple
import streamlit as st
from src import config
from src.extractor.pdf import PDFExtractor
from src.research.collections import CollectionStore
from src.extractor.identifiers import identifier_key
from src.models import SearchResult
from src.search.library import CONTENT_KINDS, IDENTIFIER_GROUP_TITLES, PROVISION_FILTERS, Library
from src.search.query import IDENTIFIER_HELP, SYNTAX_HELP
from src.research.glossary import terms_in_text
from src.ui.auth import account_menu, require_login
from src.ui.collections_tab import render_collections
from src.ui.compare_tab import render_compare
from src.ui.glossary_tab import render_glossary
from src.search import semantic
from src.search.indexer import Indexer
from src.ui.library_tab import indexing_indicator, render_library_tab
from src.ui.pins import PinContext, pin_button
from src.ui.related_panel import left_pane
from src.ui.state import (COLLECTIONS_TAB, COMPARE_TAB, GLOSSARY_TAB, LIBRARY_TAB, MAIN_TAB, SEARCH_TAB,
                          follow_identifier, replace_identifier, select_result, set_query, show_page, trail_back)
from src.ui.terms import glossary
from src.ui.viewer import render_viewer
from src.ui.tables import table_rows_html
from src.utils.formatting import highlight_values, results_to_dataframe

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
    .badge-meaning { background: #6D28D9; color: #FFFFFF; }
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
    .id-trail { font-weight: 600; }
    .exploring { font-size: 0.95rem; }
    .trail-sep { opacity: 0.5; }
    .related-group {
        font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
        opacity: 0.6; margin: 10px 0 2px;
    }
    .related-reason { font-size: 0.8rem; opacity: 0.7; font-style: italic; margin: -8px 0 2px 2px; }
    .related-findings { display: flex; flex-wrap: wrap; gap: 4px; margin: -8px 0 4px 2px; }
    .finding { font-size: 0.75rem; font-weight: 600; padding: 1px 6px; border-radius: 4px; white-space: nowrap; }
    .finding-conflict { background: #FEE2E2; color: #991B1B; }
    .finding-change { background: #FEF3C7; color: #92400E; }
    .finding-info { background: rgba(128, 128, 128, 0.15); color: inherit; }
    .finding-same { background: #DCFCE7; color: #166534; }
    .closest-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.9rem; margin-bottom: 6px; }
    .closest-pair > div { background: rgba(128, 128, 128, 0.08); padding: 6px 8px; border-radius: 4px; }
    .related-preview {
        font-size: 0.85rem; opacity: 0.75; margin: 0 0 6px; padding-left: 2px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .diff-del { background: #FEE2E2; color: #991B1B; }
    .diff-ins { background: #DCFCE7; color: #166534; text-decoration: none; }
    .badge-diff-changed { background: #B45309; color: #FFFFFF; }
    .badge-diff-added { background: #15803D; color: #FFFFFF; }
    .badge-diff-removed { background: #B91C1C; color: #FFFFFF; }
    .badge-diff-unchanged { background: rgba(128, 128, 128, 0.15); color: inherit; }
</style>
""", unsafe_allow_html=True)

_PROVISION_BADGES = {"requirement": "shall", "recommendation": "should", "permission": "may", "note": "note"}

# Nothing below renders until the user has signed in (the setup page on first run)
require_login()


# Application Dependencies
@st.cache_resource
def get_library() -> Library:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Library()


@st.cache_resource
def get_indexer() -> Indexer:
    """One background indexer for the app, shared by every browser session."""
    return Indexer()


@st.cache_resource
def warm_up_meaning_model() -> None:
    """Loads the language model in the background once, so the first search doesn't wait for it."""
    if semantic.model_files_present():
        threading.Thread(target=semantic.get_model, name="searchables-model-load", daemon=True).start()


@st.cache_resource
def get_collections() -> CollectionStore:
    return CollectionStore(get_library().conn)


library = get_library()
store = get_collections()
indexer = get_indexer()
warm_up_meaning_model()
extractor = PDFExtractor()
documents = library.list_documents()

# A link (?q=…&doc=…&page=…) restores a search and the page being viewed, once per browser session
if "session_started" not in st.session_state:
    st.session_state["session_started"] = True
    st.session_state["query"] = st.query_params.get("q", "")
    st.session_state["id_mode"] = st.query_params.get("mode") == "id"
    st.session_state["id_children"] = st.query_params.get("sub") == "1"
    try:
        # Remembered with the link's own search: it applies to that search only
        st.session_state["pending_view"] = (st.session_state["query"], int(st.query_params["doc"]),
                                            int(st.query_params["page"]))
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

    account_menu()
    indexing_indicator(indexer)

    recent = library.recent_searches()
    if recent:
        st.header("Recent searches")
        st.pills("Recent searches", recent, key="recent_pick", on_change=_pick_recent, label_visibility="collapsed")

# Main Dashboard
st.title("Standards Search")
st.caption(
    f"{len(documents)} document{'s' if len(documents) != 1 else ''} in the library · "
    "search by words and meaning, phrases, boolean operators and identifiers"
)

# Only the open tab is drawn: faster, and the page viewer (used by two tabs) never appears twice
search_tab, compare_tab, glossary_tab, collections_tab, library_tab = st.tabs(
    [SEARCH_TAB, COMPARE_TAB, GLOSSARY_TAB, COLLECTIONS_TAB, LIBRARY_TAB], key=MAIN_TAB, on_change="rerun"
)
documents_by_id = {d.id: d for d in documents}


def render_result(res, index: int, selected: bool, pin_ctx: PinContext, detail: str = "") -> None:
    block = res.block
    badges = []
    if block.is_object:
        badges.append(f'<span class="badge badge-object">{html.escape(block.label or "Untitled " + block.kind)}</span>')
    if block.clause_num:
        badges.append(f'<span class="badge badge-metric">{html.escape(block.clause_num)}</span>')
    if block.provision:
        badges.append(f'<span class="badge badge-{block.provision}">{_PROVISION_BADGES[block.provision]}</span>')
    if res.match == "meaning":
        badges.append('<span class="badge badge-meaning" title="Found by meaning: it doesn\u2019t contain '
                      'your search words">meaning</span>')
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
            if not detail:
                if res.match == "meaning":
                    detail = f"Matched by meaning ({res.similarity:.2f})"
                elif res.match == "both":
                    detail = "Matched by words and meaning"
                else:
                    detail = f"Score {res.score:.2f}"
            st.caption(f"{detail} · {res.citation}", width="stretch")
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
    if st.session_state.get("id_mode"):
        params["mode"] = "id"
        if st.session_state.get("id_children"):
            params["sub"] = "1"
    if st.session_state.get("view_doc") is not None:
        params |= {"doc": str(st.session_state["view_doc"]), "page": str(st.session_state["view_page"])}
    st.query_params.from_dict(params)


def open_pending_view(query: str) -> None:
    """
    Shows the page named in the link this session was opened with, for the link's own search only:
    any other search first discards it, so it can't take over the viewer later.
    """
    pending = st.session_state.pop("pending_view", None)
    if pending and pending[0].strip() == query.strip():
        _, doc_id, page = pending
        doc = library.get_document(doc_id)
        if doc and 1 <= page <= doc.page_count:
            show_page(doc_id, page)


def run_identifier_search(query: str, include_children: bool) -> Tuple[List[SearchResult], List[str]]:
    """Identifier matches as result cards, in group order (headings and captions, table rows, rules, mentions)."""
    hits = library.identifier_search(query, include_children, doc_ids=[d.id for d in selected_docs],
                                     kinds=kinds, provisions=provisions)
    if st.session_state.get("last_recorded") != query:
        library.record_search(query)
        st.session_state["last_recorded"] = query
    return [
        SearchResult(
            block=hit.block, score=0.0, rank=rank, doc_title=hit.doc_title,
            highlighted_text=(table_rows_html(library, hit.block, hit.rows, hit.values) if hit.group == "table"
                              else highlight_values(hit.block.text, hit.values)),
        )
        for rank, hit in enumerate(hits, 1)
    ], [hit.group for hit in hits]


def identifier_panel(query: str, include_children: bool) -> None:
    """Trail of followed identifiers, parent and sub-identifiers, and related identifiers to follow."""
    related = library.related_identifiers(query, include_children, doc_ids=[d.id for d in selected_docs])
    trail = st.session_state.get("id_trail", [query])
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(f'<div class="id-trail">{" → ".join(html.escape(t) for t in trail)}</div>', width="stretch")
            st.button("Back", key="id_back", icon=":material/arrow_back:", disabled=len(trail) < 2,
                      on_click=trail_back, help="Return to the previous identifier on the trail")
        groups = []
        if related.parent:
            groups.append(("Part of", [(related.parent, "The identifier this one extends")]))
        if related.children:
            groups.append(("Sub-identifiers", [(c, "Extends this identifier") for c in related.children]))
        if related.related:
            groups.append(("Related", [
                (r.value, f"Shares {r.same_row} table row{'s' if r.same_row != 1 else ''} and "
                          f"{r.same_passage} passage{'s' if r.same_passage != 1 else ''}")
                for r in related.related
            ]))
        if not groups:
            st.caption("No related identifiers found. Only switched-on identifier patterns are used "
                       "(Library → Manage → Identifiers).")
        for title, items in groups:
            with st.container(horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
                st.caption(title, width="content")
                for i, (value, why) in enumerate(items):
                    st.button(value, key=f"id_{title}_{i}", on_click=follow_identifier, args=(value,),
                              help=why, type="tertiary")


def show_results(query: str, results: List[SearchResult], summary: str, pin_ctx: PinContext,
                 groups: Optional[List[str]] = None, identifier: Optional[tuple] = None) -> None:
    """Results list beside the page viewer; with `groups`, a heading starts each group of identifier results."""
    selected_index = st.session_state["selected"]
    results_col, viewer_col = st.columns([2, 3], gap="medium")
    with results_col:
        # Result navigation stays visible in both modes, so Alt+Up/Down keep working while exploring
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(summary, width="stretch")
            st.button("▲ Prev", key="result_prev", disabled=selected_index == 0,
                      on_click=select_result, args=(selected_index - 1,),
                      shortcut="Alt+Up", help="Previous result")
            st.button("Next ▼", key="result_next", disabled=selected_index >= len(results) - 1,
                      on_click=select_result, args=(selected_index + 1,),
                      shortcut="Alt+Down", help="Next result")

        def result_list() -> None:
            if identifier:
                identifier_panel(*identifier)
            # Fixed-height pane scrolls on its own, so the page viewer stays in view
            with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
                for i, res in enumerate(results):
                    group = groups[i] if groups else None
                    if group and (i == 0 or groups[i - 1] != group):
                        count = groups.count(group)
                        st.markdown(f"**{IDENTIFIER_GROUP_TITLES[group]}** · {count}")
                    render_result(res, i, i == selected_index, pin_ctx,
                                  detail=IDENTIFIER_GROUP_TITLES[group] if group else "")

            st.download_button(
                label="Download Results (CSV)",
                data=results_to_dataframe(results).to_csv(index=False),
                file_name="search_results.csv",
                mime="text/csv",
            )

        left_pane(library, result_list)

    with viewer_col:
        with st.container(border=True):
            render_viewer(library, query, results[selected_index].block, pin_ctx, identifier=identifier)


if search_tab.open:
    with search_tab:
        if not documents:
            st.info("The library is empty. Add standards in the **Library** tab to start searching.")
        else:
            query_col, mode_col, help_col = st.columns([6, 1.4, 1], vertical_alignment="bottom")
            # Widget state is discarded while another tab is open, so "query" and "id_mode" are the source of truth
            id_mode = mode_col.toggle(
                "Identifier", value=st.session_state.get("id_mode", False), key="id_mode_input",
                help="Search for an identifier (a message label, field, requirement or part number…) "
                     "instead of words: exact matches, grouped by role, with related identifiers",
            )
            st.session_state["id_mode"] = id_mode
            query = query_col.text_input(
                "Search the library",
                value=st.session_state.get("query", ""),
                key="query_input",
                placeholder="An identifier, e.g. a message label, field or part number" if id_mode
                else 'e.g. "shall not exceed" calibration -software',
            )
            st.session_state["query"] = query
            with help_col.popover("Syntax", width="stretch"):
                st.markdown(IDENTIFIER_HELP if id_mode else SYNTAX_HELP)

            include_children = False
            if id_mode:
                include_children = st.checkbox(
                    "Include sub-identifiers", value=st.session_state.get("id_children", False), key="id_children_input",
                    help="Also match identifiers that extend this one (e.g. a message's words or sub-parts)",
                )
                st.session_state["id_children"] = include_children
                # Typing an identifier starts a new trail; following one from the panel extends it
                trail = st.session_state.get("id_trail", [])
                if query.strip() and (not trail or identifier_key(trail[-1]) != identifier_key(query)):
                    st.session_state["id_trail"] = [query.strip()]

            pin_ctx = PinContext(library, store, active.id, query, store.pinned_keys(active.id))
            groups = None
            if not query.strip():
                results = None
            elif id_mode:
                results, groups = run_identifier_search(query, include_children)
                outdated = [d for d in library.outdated_documents() if not selected_docs or d in selected_docs]
                if outdated:
                    st.info(f"{len(outdated)} document(s) in scope were indexed by an older version and may miss "
                            "identifiers. Re-index them in the Library tab.", icon=":material/update:")
                if not results:
                    st.warning(f"No passages contain the identifier “{query.strip()}” in the current scope.")
                    suggestions = library.identifier_suggestions(query, doc_ids=[d.id for d in selected_docs])
                    if suggestions:
                        with st.container(horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
                            st.caption("Did you mean", width="content")
                            for i, value in enumerate(suggestions):
                                st.button(value, key=f"suggest_{i}", on_click=replace_identifier, args=(value,),
                                          type="tertiary")
            else:
                outcome = run_search(query)
                results = outcome[0] if outcome else None
                if outcome and not results:
                    st.warning("No passages match. Try fewer words, a prefix like `calib*`, OR between "
                               "alternatives, or fewer filters.")

            if results:
                # A new search (or scope/order/mode change) starts the viewer on the first result
                search_key = (query, id_mode, include_children, tuple(d.id for d in selected_docs), document_order,
                              max_results, tuple(kinds), tuple(provisions))
                st.session_state["result_locations"] = [(r.block.doc_id, r.block.page, r.block.id) for r in results]
                if (
                    st.session_state.get("search_key") != search_key
                    or st.session_state.get("selected", 0) >= len(results)  # Library changed under the same search
                ):
                    st.session_state["search_key"] = search_key
                    select_result(0)
                    open_pending_view(query)
                if id_mode:
                    passages = f"{len(results)} passage{'s' if len(results) != 1 else ''}"
                    show_results(query, results, f"**{query.strip()}** appears in **{passages}**", pin_ctx,
                                 groups=groups, identifier=(query, include_children))
                else:
                    show_results(query, results, f"Showing **{len(results)}** of **{outcome[1]}** matching passages",
                                 pin_ctx)
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
        render_library_tab(library, extractor, documents, indexer)
