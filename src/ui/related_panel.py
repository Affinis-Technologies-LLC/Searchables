"""
The left pane's Related view: passages connected to the one being explored, beside the page viewer.

The explored passage ("focus") follows what you click: a search result, a passage's Related button in
the viewer's Text tab, or a related passage. Every tab with a page viewer puts a Results | Related
switch at the top of its left pane (see `left_pane`).
"""
import html
from typing import Callable, Dict, List, Optional

import streamlit as st

from src import config
from src.models import RelatedPassage, TextBlock
from src.research.glossary import terms_in_text
from src.search.library import RELATED_GROUPS, Library
from src.ui.state import (PANE_RELATED, PANE_RESULTS, PassageStop, follow_passage, jump_to_trail, set_pane)
from src.ui.terms import glossary


def current_focus(library: Library) -> Optional[TextBlock]:
    """
    The passage being explored on the page in view: the focused one if it's there, else the outlined
    one (a followed reference or opened pin), else the first passage of body text on the page.
    """
    doc_id, page = st.session_state.get("view_doc"), st.session_state.get("view_page")
    if doc_id is None or page is None:
        return None
    blocks = library.page_blocks(doc_id, page)
    by_id = {b.id: b for b in blocks}
    focus_id = st.session_state.get("focus_block")
    if focus_id in by_id:
        return by_id[focus_id]
    target = st.session_state.get("view_target")
    if target and target[:2] == (doc_id, page):
        outlined = next((b for b in blocks if b.bbox == target[2]), None)
        if outlined:
            return outlined
    return next((b for b in blocks if b.kind != "heading"), blocks[0] if blocks else None)


def related_for(library: Library, focus: Optional[TextBlock]) -> Dict[str, List[RelatedPassage]]:
    if focus is None:
        return {}
    doc = library.get_document(focus.doc_id)
    terms = terms_in_text(glossary(library, doc), focus.text) if doc and focus.kind == "text" else []
    return library.related_passages(focus, terms)


def stop_for(block: TextBlock) -> PassageStop:
    """A trail entry for a passage: where it is, and a short name for the breadcrumb."""
    name = block.label or block.clause_num or (block.text[:24] + "…" if len(block.text) > 24 else block.text)
    return block.doc_id, block.page, block.bbox, block.id, f"{name} (p. {block.display_page})"


def left_pane(library: Library, render_results: Callable[[], None]) -> None:
    """
    Results | Related switch, then either the tab's own list (`render_results`) or the Related view.
    The choice is kept in "pane" (widget state is discarded while a tab isn't drawn).
    """
    focus = current_focus(library)
    related = related_for(library, focus)
    count = sum(len(items) for items in related.values())
    # The switch's state is discarded while its tab isn't drawn; restore it from "pane" when that happens
    if "pane_input" not in st.session_state:
        st.session_state["pane_input"] = st.session_state.get("pane", PANE_RESULTS)
    mode = st.segmented_control(
        "Show", [PANE_RESULTS, PANE_RELATED], key="pane_input", label_visibility="collapsed", width="stretch",
        format_func=lambda m: f"Related ({count})" if m == PANE_RELATED else m,
    ) or PANE_RESULTS  # None when the active option is clicked again
    st.session_state["pane"] = mode
    if mode == PANE_RELATED:
        _related_view(focus, related)
    else:
        render_results()


def _related_view(focus: Optional[TextBlock], related: Dict[str, List[RelatedPassage]]) -> None:
    if focus is None:
        st.info("Select a result or open a page to explore what's related to its passages.")
        return

    # What's being explored, and a way back to the results list
    with st.container(horizontal=True, vertical_alignment="center"):
        name = html.escape(focus.label or focus.clause or focus.text[:60])
        st.html(f'<div class="exploring">Exploring <strong>{name}</strong> · p. {html.escape(focus.display_page)}</div>',
                width="stretch")
        st.button("", key="explore_close", icon=":material/close:", type="tertiary",
                  on_click=set_pane, args=(PANE_RESULTS,), help="Back to the results")
    st.caption("To explore another passage, use its **Related** button in the viewer's Text tab.")

    trail = st.session_state.get("passage_trail", [])
    if len(trail) > 1:
        with st.container(horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
            for i, stop in enumerate(trail):
                if i:
                    st.html('<span class="trail-sep">›</span>', width="content")
                current = i == len(trail) - 1
                st.button(stop[4], key=f"trail_{i}", type="tertiary", disabled=current,
                          on_click=jump_to_trail, args=(i,),
                          help=None if current else "Go back to this passage")

    if not related:
        st.caption("Nothing related found: no references, shared identifiers, defined terms or similar wording.")
        return

    origin = stop_for(focus)
    with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
        for group, items in related.items():
            st.html(f'<div class="related-group">{html.escape(RELATED_GROUPS[group])}</div>')
            for i, item in enumerate(items):
                _related_item(item, f"{group}_{i}", origin, focus.doc_id)


# Assessment findings, coloured by how much they matter to someone comparing requirements
_FINDING_STYLE = {
    "Possible conflict": "finding-conflict",
    "Stronger requirement": "finding-change",
    "Weaker requirement": "finding-change",
    "Different value": "finding-change",
    "Different identifiers": "finding-info",
    "Same content": "finding-same",
}


def _findings_html(item: RelatedPassage) -> str:
    if not item.findings:
        return f'<div class="related-reason">{html.escape(item.reason)}</div>'
    badges = "".join(
        f'<span class="finding {_FINDING_STYLE.get(f.label, "finding-info")}" title="{html.escape(f.detail)}">'
        f'{html.escape(f.label)}{": " + html.escape(f.detail) if f.detail and f.label != "Different identifiers" else ""}</span>'
        for f in item.findings
    )
    return f'<div class="related-findings">{badges}</div>'


def _related_item(item: RelatedPassage, key: str, origin: PassageStop, focus_doc: int) -> None:
    """One line to click (title and reason or findings), a one-line preview, and a quick look."""
    block = item.block
    where = f"{item.doc_title} · " if block.doc_id != focus_doc else ""
    title = f"{where}{block.label or block.clause or 'Passage'} · p. {block.display_page}"
    with st.container(horizontal=True, wrap=False, vertical_alignment="center", gap="small"):
        st.button(title, key=f"related_{key}", type="tertiary", on_click=follow_passage,
                  args=(stop_for(block), origin), help="Open this passage and explore what it's related to",
                  width="stretch")
        with st.popover("", icon=":material/visibility:", help="Quick look at the whole passage"):
            st.caption(f"{item.doc_title} · p. {block.display_page}" + (f" · {block.clause_path}" if block.clause_path else ""))
            if item.closest:
                # The corresponding sentences side by side: what the assessment compared
                st.html(
                    '<div class="closest-pair">'
                    f'<div><small>This passage</small><br>{html.escape(item.closest[0])}</div>'
                    f'<div><small>That passage</small><br>{html.escape(item.closest[1])}</div></div>'
                )
                for finding in item.findings:
                    if finding.detail:
                        st.caption(f"**{finding.label}:** {finding.detail}")
            st.html(f'<div class="result-body">{html.escape(block.text)}</div>')
            st.button("Open", key=f"peek_{key}", type="primary", on_click=follow_passage,
                      args=(stop_for(block), origin))
    # Findings (or the reason) on their own line, so long ones don't squeeze the title; then a preview.
    # For same-topic matches the matching sentence says more than the passage's opening words.
    preview_text = item.closest[1] if item.closest else block.text
    preview = preview_text[:110] + ("…" if len(preview_text) > 110 else "")
    st.html(_findings_html(item) + f'<div class="related-preview">{html.escape(preview)}</div>')
