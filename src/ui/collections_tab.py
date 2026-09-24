"""The Collections tab: pinned items with notes, a page viewer, and export."""
import html
import re

import pandas as pd
import streamlit as st

from src import config
from src.models import Collection, Pin
from src.research.collections import CollectionStore
from src.research.export import to_docx, to_markdown
from src.search.library import Library
from src.ui.pins import PinContext
from src.ui.state import show_page
from src.ui.viewer import render_viewer


def _view_pin(pin: Pin) -> None:
    show_page(pin.doc_id, pin.page, pin.bbox)
    st.session_state["viewing_pin_query"] = pin.query


def _save_note(store: CollectionStore, pin_id: int) -> None:
    store.update_note(pin_id, st.session_state.get(f"note_{pin_id}", ""))


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "", name).strip() or "collection"


def render_collections(library: Library, store: CollectionStore, collection: Collection, pin_ctx: PinContext) -> None:
    pins = store.pins(collection.id)
    live_docs = {d.id for d in library.list_documents()}

    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.subheader(collection.name, width="stretch")
        filename = _safe_filename(collection.name)
        st.download_button("Word", to_docx(collection.name, pins) if pins else b"", icon=":material/description:",
                           file_name=f"{filename}.docx", disabled=not pins,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        st.download_button("Markdown", to_markdown(collection.name, pins) if pins else "", icon=":material/download:",
                           file_name=f"{filename}.md", mime="text/markdown", disabled=not pins)
        _manage(store, collection)

    if not pins:
        st.info("Nothing pinned yet. Use **Pin** on a search result, table or figure to collect it here.")
        return

    list_col, viewer_col = st.columns([2, 3], gap="medium")
    with list_col:
        st.caption(f"{len(pins)} pinned item{'s' if len(pins) != 1 else ''}, oldest first")
        with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
            for pin in pins:
                _pin_card(store, pin, available=pin.doc_id in live_docs)
    with viewer_col:
        with st.container(border=True):
            render_viewer(library, st.session_state.get("viewing_pin_query", ""), None, pin_ctx)


def _pin_card(store: CollectionStore, pin: Pin, available: bool) -> None:
    with st.container(border=True):
        badge = f'<span class="badge badge-object">{html.escape(pin.label)}</span>' if pin.label else ""
        st.html(
            f'<div class="result-head"><span class="badge badge-page">p. {html.escape(pin.page_label)}</span>'
            f'{badge}<span class="result-doc">{html.escape(pin.doc_title)}</span></div>'
            f'<div class="result-path">{html.escape(pin.clause) or "&nbsp;"}</div>'
        )
        if pin.table:
            if pin.table.get("caption"):
                st.caption(pin.table["caption"])
            st.dataframe(pd.DataFrame(pin.table["rows"], columns=pin.table["columns"]), hide_index=True, width="stretch")
        else:
            st.html(f'<div class="result-body pin-quote">{html.escape(pin.text)}</div>')

        st.text_area("Note", value=pin.note, key=f"note_{pin.id}", placeholder="Why this matters, open questions…",
                     on_change=_save_note, args=(store, pin.id), height=68, label_visibility="collapsed")
        with st.container(horizontal=True, vertical_alignment="center"):
            found = f"Found by “{pin.query}”" if pin.query else ""
            if not available:
                found = "Document no longer in the library; text and citation kept"
            st.caption(found, width="stretch")
            st.button("View page", key=f"view_pin_{pin.id}", disabled=not available, on_click=_view_pin,
                      args=(pin,), width="content")
            st.button("Remove", key=f"remove_pin_{pin.id}", on_click=store.remove_pin, args=(pin.id,),
                      width="content")


def _manage(store: CollectionStore, collection: Collection) -> None:
    with st.popover("Manage", icon=":material/settings:"):
        new_name = st.text_input("Rename", value=collection.name, key=f"rename_{collection.id}")
        if st.button("Save name", disabled=new_name.strip() == collection.name):
            try:
                store.rename(collection.id, new_name)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        st.divider()
        st.write(f"Delete **{collection.name}** and its {collection.pin_count} pin"
                 f"{'s' if collection.pin_count != 1 else ''}?")
        if st.button("Delete collection", type="primary"):
            store.delete(collection.id)
            st.session_state.pop("active_collection", None)
            st.rerun()
