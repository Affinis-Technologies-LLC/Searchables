"""The page viewer: page image with highlights, page text, tables & figures, and cross-references."""
import base64
import html
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

from src import config
from src.models import CrossRef, Document, ResolvedRef, Term, TextBlock
from src.research.glossary import terms_in_text
from src.search.library import Library
from src.ui.pins import PinContext, pin_button
from src.ui.related_panel import current_focus, stop_for
from src.ui.state import explore_passage, jump_to_page, show_page, step_page
from src.ui.tables import table_frame, table_html
from src.ui.terms import glossary
from src.utils.formatting import highlight_values
from src.viewer.render import RenderedPage, render_page


@st.cache_data(max_entries=64, show_spinner=False)
def cached_page_render(pdf_path: str, page: int, terms: tuple, target, zoom: float, clip=None) -> RenderedPage:
    return render_page(Path(pdf_path), page, terms, target, zoom, clip)


def render_viewer(
    library: Library,
    query: str,
    selected: Optional[TextBlock] = None,
    pin_ctx: Optional[PinContext] = None,
    identifier: Optional[Tuple[str, bool]] = None,
) -> None:
    """
    Shows the page in session state ("view_doc"/"view_page"). `selected` is outlined when it's on
    that page; a followed reference or opened pin ("view_target") takes precedence. With
    `identifier` (text, include sub-identifiers), that identifier is highlighted instead of `query`.
    """
    doc = library.get_document(st.session_state.get("view_doc", -1))
    if doc is None:
        st.info("Select a result or pin to view its page.")
        return
    page = st.session_state["view_page"]
    on_selected_page = selected is not None and selected.doc_id == doc.id and selected.page == page

    view_target = st.session_state.get("view_target")
    if view_target and view_target[:2] == (doc.id, page):
        outline, outlined_id = view_target[2], None
    elif on_selected_page:
        outline, outlined_id = selected.bbox, selected.id
    else:
        outline, outlined_id = None, None

    blocks = library.page_blocks(doc.id, page)
    page_label = next((b.display_page for b in blocks), str(page))
    focus = current_focus(library)
    clause_path = focus.clause_path if focus else ""
    hit_pages, terms, matches = _page_hits(library, doc, page, blocks, query, identifier)

    st.html(
        f'<div class="result-head"><span class="badge badge-page">p. {html.escape(page_label)}</span>'
        f'<span class="result-doc">{html.escape(doc.title)}</span>'
        f'<span class="viewer-count">page {page} of {doc.page_count}</span></div>'
        f'<div class="result-path">{html.escape(clause_path) or "&nbsp;"}</div>'
    )
    zoom = _navigation(doc, page, hit_pages)

    objects = [b for b in blocks if b.is_object]
    outgoing = library.page_refs(doc.id, page)
    incoming = library.referenced_from(doc.id, page)
    page_terms = terms_in_text(glossary(library, doc), " ".join(b.text for b in blocks))
    page_tab, text_tab, objects_tab, refs_tab, terms_tab = st.tabs([
        "Page", "Text",
        f"Tables & figures ({len(objects)})" if objects else "Tables & figures",
        f"References ({len(outgoing) + len(incoming)})" if outgoing or incoming else "References",
        f"Terms ({len(page_terms)})" if page_terms else "Terms",
    ])
    pdf_path = str(library.pdf_path(doc.sha256))

    with page_tab:
        rendered = cached_page_render(
            pdf_path, page, terms, outline,
            min(config.VIEWER_RENDER_SCALE * zoom, config.VIEWER_MAX_RENDER_SCALE),
        )
        # Displayed at a percentage of the pane width inside a scrolling frame, so zooming in
        # enlarges the page and lets you pan, rather than just sharpening a fitted image
        encoded = base64.b64encode(rendered.png).decode("ascii")
        st.html(
            f'<div class="page-frame"><img src="data:image/png;base64,{encoded}" '
            f'style="width: {int(zoom * 100)}%; max-width: none;" alt="Page {page}"></div>'
        )
        if terms:
            notes = [f"{rendered.hit_count} highlight{'s' if rendered.hit_count != 1 else ''} on this page"]
            if not rendered.hit_count:
                # Scanned page without OCR, or a word split across lines in the PDF
                notes = ["Matched words couldn't be located on the page image; the outlined passage shows the match"]
            if hit_pages:
                notes.append(f"matches on {len(hit_pages)} page{'s' if len(hit_pages) != 1 else ''} of this document")
            st.caption(" · ".join(notes))

    with text_tab:
        _page_text(library, blocks, matches, focus.id if focus else outlined_id)
    with objects_tab:
        _objects(library, doc, objects, pdf_path, pin_ctx)
    with refs_tab:
        _references(doc, outgoing, incoming)
    with terms_tab:
        _terms(doc, page_terms)


def _navigation(doc: Document, page: int, hit_pages: List[int]) -> float:
    """Page, hit-page, go-to and zoom controls. Returns the zoom level."""
    earlier = [p for p in hit_pages if p < page]
    later = [p for p in hit_pages if p > page]
    # Buttons flow at their natural width; fixed columns squeezed the labels behind the shortcut hints
    with st.container(horizontal=True, wrap=True, vertical_alignment="bottom"):
        st.button("◀ Page", key="page_prev", disabled=page <= 1, on_click=step_page,
                  args=(-1, doc.page_count), shortcut="Alt+Left")
        st.button("Page ▶", key="page_next", disabled=page >= doc.page_count, on_click=step_page,
                  args=(1, doc.page_count), shortcut="Alt+Right")
        st.button("◀ Hit page", key="hit_prev", disabled=not earlier, on_click=show_page,
                  args=(doc.id, earlier[-1] if earlier else page), shortcut="Alt+Shift+Left",
                  help="Previous page in this document with a match")
        st.button("Hit page ▶", key="hit_next", disabled=not later, on_click=show_page,
                  args=(doc.id, later[0] if later else page), shortcut="Alt+Shift+Right",
                  help="Next page in this document with a match")
        st.number_input("Go to page", min_value=1, max_value=doc.page_count, step=1, key="page_input",
                        on_change=jump_to_page, width=110)
        # Widget state is discarded while its tab isn't drawn, so the level is kept separately
        zoom = st.segmented_control(
            "Zoom", options=config.VIEWER_ZOOM_LEVELS, key="zoom",
            default=st.session_state.get("zoom_level", config.VIEWER_ZOOM_LEVELS[0]),
            format_func=lambda z: "Fit" if z == 1 else f"{int(z * 100)}%",
        ) or 1.0  # None when the user deselects the active level
    st.session_state["zoom_level"] = zoom
    return zoom


def _page_hits(library: Library, doc: Document, page: int, blocks: List[TextBlock], query: str,
               identifier: Optional[Tuple[str, bool]]) -> Tuple[List[int], tuple, Dict[int, str]]:
    """
    Pages of the document with a hit, the words to highlight on the page image, and matching
    blocks on this page as highlighted HTML: for an identifier search, or a word search.
    """
    if identifier:
        text, include_children = identifier
        values_by_block = library.identifier_values_on_page(doc.id, page, text, include_children)
        texts = {b.id: b.text for b in blocks}
        matches = {bid: highlight_values(texts[bid], values) for bid, values in values_by_block.items() if bid in texts}
        terms = tuple(sorted({v for values in values_by_block.values() for v in values}, key=len, reverse=True))
        return library.identifier_pages(doc.id, text, include_children), terms, matches
    if query.strip():
        return (library.hit_pages(query, doc.id), tuple(library.page_hit_terms(query, doc.id, page)),
                library.page_matches(query, doc.id, page))
    return [], (), {}


def _page_text(library: Library, blocks: List[TextBlock], matches: Dict[int, str], outlined_id: Optional[int]) -> None:
    """The page's passages, each with a Related button that explores from it in the left pane."""
    if not blocks:
        st.html("<p>No text on this page.</p>")
        return
    for block in blocks:
        css = ["context-block"]
        if block.kind == "heading":
            css.append("context-heading")
        if block.id in matches:
            css.append("context-hit")
        if block.id == outlined_id:
            css.append("context-target")
        if block.kind == "table":
            body = table_html(library, block)  # Selectable cells instead of the flattened index text
        elif block.kind == "figure":
            body = f"<em>[{html.escape(block.text)}]</em>"
        else:
            body = matches.get(block.id, html.escape(block.text))
        # wrap=False keeps each passage's Related button beside it rather than on a line of its own
        with st.container(horizontal=True, wrap=False, vertical_alignment="top", gap="small"):
            st.html(f'<div class="{" ".join(css)}">{body}</div>', width="stretch")
            st.button("", key=f"explore_{block.id}", icon=":material/hub:", type="tertiary",
                      on_click=explore_passage, args=(stop_for(block),),
                      help="Related: explore what this passage connects to")


def _objects(library: Library, doc: Document, objects: List[TextBlock], pdf_path: str,
             pin_ctx: Optional[PinContext]) -> None:
    if not objects:
        st.caption("No tables or figures detected on this page.")
        return
    for block in objects:
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{block.label or 'Untitled ' + block.kind}**", width="stretch")
                if pin_ctx:
                    citation = ", ".join(p for p in (doc.title, block.label, f"p. {block.display_page}") if p)
                    pin_button(pin_ctx, block, doc.title, citation, key=f"pin_obj_{block.id}")
                st.button("Show on page", key=f"obj_{block.id}", on_click=show_page,
                          args=(doc.id, block.page, block.bbox), width="content")
            if block.kind == "table":
                frame, pages = table_frame(library, block)
                if len(pages) > 1:
                    st.caption(f"Joined from pages {', '.join(map(str, pages))}")
                st.dataframe(frame, hide_index=True, width="stretch")
                st.download_button("Download CSV", frame.to_csv(index=False), key=f"csv_{block.id}",
                                   file_name=f"{doc.title} {block.label or 'table'}.csv", mime="text/csv")
            else:
                crop = cached_page_render(pdf_path, block.page, (), None, config.VIEWER_RENDER_SCALE, block.bbox)
                st.image(crop.png, width="stretch")


def _references(doc: Document, outgoing: List[ResolvedRef], incoming: List[Tuple[CrossRef, TextBlock]]) -> None:
    st.markdown("**Referenced on this page**")
    if not outgoing:
        st.caption("None found.")
    for i, ref in enumerate(outgoing):
        target = ref.ref.target if ref.ref.kind != "clause" else f"Clause {ref.ref.target}"
        if ref.doc_id is None:
            where = "not in the library" if ref.ref.kind == "standard" else "not found in this document"
        elif ref.doc_id != doc.id:
            where = f"opens {ref.doc_title}"
        else:
            where = f"page {ref.page}"
        with st.container(horizontal=True, vertical_alignment="center"):
            st.html(f"{html.escape(target)} · <small>{html.escape(where)}</small>", width="stretch")
            st.button("Go", key=f"ref_out_{i}", disabled=ref.doc_id is None, on_click=show_page,
                      args=(ref.doc_id, ref.page, ref.bbox), width="content")

    st.markdown("**Refers to this page**")
    if not incoming:
        st.caption("Nothing elsewhere in this document refers to the clauses, tables or figures on this page.")
    for i, (ref, block) in enumerate(incoming):
        name = ref.target if ref.kind != "clause" else f"Clause {ref.target}"
        source = block.label or block.clause or "Untitled passage"
        with st.container(horizontal=True, vertical_alignment="center"):
            # st.html, not st.markdown: PDF text can contain "$", which markdown renders as math
            st.html(
                f"{html.escape(name)} ← {html.escape(source)}, page {block.page}<br>"
                f"<small>{html.escape(block.text[:140])}{'…' if len(block.text) > 140 else ''}</small>",
                width="stretch",
            )
            st.button("Go", key=f"ref_in_{i}", on_click=show_page,
                      args=(doc.id, block.page, block.bbox), width="content")


def _terms(doc: Document, terms: List[Term]) -> None:
    if not terms:
        st.caption("No terms defined in this document's terms and definitions clause appear on this page.")
        return
    for term in terms:
        with st.container(horizontal=True, vertical_alignment="center"):
            also = f" <small>(also: {html.escape(', '.join(term.synonyms))})</small>" if term.synonyms else ""
            st.html(
                f"<strong>{html.escape(term.term)}</strong>{also} · <small>{html.escape(term.clause_num)}</small><br>"
                f"{html.escape(term.definition)}",
                width="stretch",
            )
            st.button("Go", key=f"term_{term.clause_num}", on_click=show_page,
                      args=(doc.id, term.page, term.bbox), help="Open where this term is defined", width="content")

