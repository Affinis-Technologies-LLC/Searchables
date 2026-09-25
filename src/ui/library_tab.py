"""The Library tab: add, re-index, rename and delete documents; indexing runs in the background."""
import sys
from typing import List

import pandas as pd
import streamlit as st

from src.extractor.pdf import PDFExtractor
from src.models import Document
from src.search.indexer import ADD, EMBED, FAILED, REINDEX, Indexer
from src.search.library import Library


def _queue(indexer: Indexer, kind: str, docs: List[Document]) -> None:
    for doc in docs:
        indexer.submit(kind, doc.title, doc_id=doc.id)


def render_library_tab(library: Library, extractor: PDFExtractor, documents: List[Document], indexer: Indexer) -> None:
    if not extractor.use_ocr:
        if sys.platform == "win32":
            how = ("Install Tesseract (the UB Mannheim build), then re-run `deploy\\windows\\install-service.ps1` "
                   "or set `TESSDATA_PREFIX` to its `tessdata` folder, and restart the app.")
        else:
            how = "Install it with `brew install tesseract` (macOS) or `apt install tesseract-ocr` (Linux) and restart the app."
        st.warning(f"Tesseract OCR was not found, so scanned pages can't be read. {how}")

    pending = indexer.pending_doc_ids()
    outdated = [d for d in library.outdated_documents() if d.id not in pending]
    if outdated:
        plural = len(outdated) != 1
        with st.container(border=True):
            st.warning(
                f"{len(outdated)} document{'s were' if plural else ' was'} indexed by an older version and "
                f"{'are' if plural else 'is'} missing newer features: tables, figures, cross-references, "
                "military-style formatting, identifier discovery and meaning search."
            )
            st.button(f"Re-index {len(outdated)} document{'s' if plural else ''}", type="primary",
                      on_click=_queue, args=(indexer, REINDEX, outdated))

    missing_meaning = [d for d in library.documents_without_meaning() if d.id not in pending]
    if missing_meaning:
        plural = len(missing_meaning) != 1
        with st.container(border=True):
            st.info(
                f"{len(missing_meaning)} document{'s' if plural else ''} can't be searched by meaning yet. "
                "Adding it reads each passage with the local language model: a few minutes for a typical "
                "standard, longer for very large ones. It runs in the background."
            )
            st.button(f"Add meaning search to {len(missing_meaning)} document{'s' if plural else ''}",
                      on_click=_queue, args=(indexer, EMBED, missing_meaning))

    with st.form("add_documents", clear_on_submit=True):
        uploads = st.file_uploader("Add standards (PDF)", type=["pdf"], accept_multiple_files=True)
        submitted = st.form_submit_button("Add to library", type="primary")
    if submitted and uploads:
        for upload in uploads:
            indexer.submit(ADD, upload.name, file_bytes=upload.getvalue())
        st.rerun()  # Show the queue straight away

    indexing_panel(indexer)

    if not documents:
        st.caption("No documents yet.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Title": d.title,
                    "File": d.filename,
                    "Pages": d.page_count,
                    "Passages": d.block_count,
                    "OCR pages": d.ocr_pages,
                    "Meaning search": "yes" if d.embedding_model else "not yet",
                    "Added": d.added_at.replace("T", " "),
                }
                for d in documents
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Manage")
    target = st.selectbox("Document", documents, format_func=lambda d: d.title)
    rename_col, reindex_col, delete_col = st.columns([4, 1, 1], vertical_alignment="bottom")
    new_title = rename_col.text_input("Title", value=target.title, key=f"title_{target.id}")
    if new_title.strip() and new_title.strip() != target.title:
        if rename_col.button("Save title"):
            library.rename_document(target.id, new_title)
            st.rerun()

    busy = target.id in pending
    reindex_col.button("Re-index", width="stretch", disabled=busy, on_click=_queue, args=(indexer, REINDEX, [target]),
                       help="Already queued" if busy else "Re-extract from the stored PDF (runs in the background)")

    with delete_col.popover("Delete…", width="stretch", disabled=busy):
        st.write(f"Remove **{target.title}** and its index from the library? Pins keep their text and citation.")
        if st.button("Delete permanently", type="primary"):
            library.delete_document(target.id)
            st.rerun()

    _identifiers_panel(library, target)


@st.fragment(run_every="2s")
def indexing_panel(indexer: Indexer) -> None:
    """Live progress of background indexing (the sidebar indicator refreshes the app when a job finishes)."""
    active, finished = indexer.active(), indexer.finished()
    if not active and not finished:
        return
    with st.container(border=True):
        st.markdown("**Indexing**")
        for job in active:
            label = {ADD: "Adding", REINDEX: "Re-indexing", EMBED: "Adding meaning search to"}[job.kind]
            if job.status == "running" and job.total:
                st.progress(job.fraction, text=f"{label} {job.name}: {job.stage.lower()} {job.done:,} of {job.total:,}")
            elif job.status == "running":
                st.progress(0.0, text=f"{label} {job.name}: starting (loading the language model the first time)…")
            else:
                st.caption(f"Waiting: {label.lower()} {job.name}")
        for job in reversed(finished[-5:]):
            if job.status == FAILED:
                st.error(f"{job.name}: {job.result}")
            else:
                st.success(job.result)
            if job.warning:
                st.warning(job.warning)


def _identifiers_panel(library: Library, doc: Document) -> None:
    st.subheader("Identifiers")
    st.caption(
        "Identifier patterns are discovered from the document itself: a pattern (# stands for any number) "
        "with several different values used across passages, such as message labels or field numbers. "
        "Switch patterns on or off here; your choices are kept when the document is re-indexed."
    )
    if doc.extract_version < 3:
        st.info("Re-index this document to discover its identifiers.")
        return
    families = library.identifier_families(doc.id)
    if not families:
        st.caption("No identifier-like patterns found in this document.")
        return

    frame = pd.DataFrame([
        {
            "Use": f.enabled,
            "Pattern": f.display,
            "Values": f.distinct_values,
            "Passages": f.passages,
            "Examples": f.examples,
            "Setting": "automatic" if f.user_enabled is None else "your choice",
        }
        for f in families
    ])
    edited = st.data_editor(
        frame, key=f"families_{doc.id}", hide_index=True, width="stretch",
        disabled=["Pattern", "Values", "Passages", "Examples", "Setting"],
        column_config={"Use": st.column_config.CheckboxColumn("Use", help="Treat this pattern as identifiers")},
    )
    changed = False
    for family, use in zip(families, edited["Use"]):
        if bool(use) != family.enabled:
            # Matching discovery's own verdict returns the family to automatic
            library.set_family_enabled(doc.id, family.family, None if bool(use) == family.auto_enabled else bool(use))
            changed = True
    if changed:
        st.rerun()

    if any(f.user_enabled is not None for f in families):
        if st.button("Reset all to automatic", key=f"reset_families_{doc.id}"):
            library.reset_families(doc.id)
            st.session_state.pop(f"families_{doc.id}", None)
            st.rerun()


@st.fragment(run_every="2s")
def indexing_indicator(indexer: Indexer) -> None:
    """Sidebar status while indexing runs; refreshes the whole app once when a job finishes."""
    active, finished = indexer.active(), indexer.finished()
    if "indexing_seen" not in st.session_state:
        st.session_state["indexing_seen"] = len(finished)  # Jobs finished before this page opened
    elif len(finished) > st.session_state["indexing_seen"]:
        st.session_state["indexing_seen"] = len(finished)
        st.rerun(scope="app")  # New or changed documents: refresh lists, the sidebar and every tab
    running = next((j for j in active if j.status == "running"), None)
    if running:
        waiting = len(active) - 1
        st.progress(running.fraction, text=f"Indexing {running.name}" + (f" (+{waiting} waiting)" if waiting else ""))
