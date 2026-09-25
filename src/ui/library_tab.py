"""The Library tab: add, re-index, rename and delete documents."""
import sys
from typing import List

import pandas as pd
import streamlit as st

from src.extractor.pdf import PDFExtractor
from src.models import Document
from src.search.library import Library


def _reindex(library: Library, extractor: PDFExtractor, docs: List[Document]) -> None:
    """Re-extracts documents from their stored PDFs, then reruns to show the outcome."""
    messages = []
    for doc in docs:
        progress = st.progress(0.0, text=f"Re-indexing {doc.title}…")

        def on_progress(done: int, total: int, name=doc.title, bar=progress) -> None:
            bar.progress(done / total, text=f"Re-indexing {name}: page {done} of {total}")

        try:
            extracted = library.reindex_document(doc.id, extractor, on_progress)
            messages.append(("success", f"Re-indexed **{doc.title}**: {len(extracted.blocks)} passages, "
                                        f"{len(extracted.tables)} tables, {len(extracted.xrefs)} cross-references"))
        except ValueError as e:
            messages.append(("error", str(e)))
        finally:
            progress.empty()
    st.session_state["ingest_messages"] = messages
    st.rerun()


def _add(library: Library, extractor: PDFExtractor, uploads) -> None:
    messages = []  # (kind, text): shown after the rerun below
    for upload in uploads:
        progress = st.progress(0.0, text=f"Reading {upload.name}…")

        def on_progress(done: int, total: int, name=upload.name, bar=progress) -> None:
            bar.progress(done / total, text=f"Reading {name}: page {done} of {total}")

        try:
            doc, extracted = library.add_document(upload.getvalue(), upload.name, extractor, on_progress)
        except ValueError as e:
            messages.append(("error", str(e)))
            continue
        finally:
            progress.empty()

        if extracted is None:
            messages.append(("info", f"**{upload.name}** is already in the library as “{doc.title}”."))
            continue

        notes = [f"{doc.page_count} pages", f"{doc.block_count} passages"]
        if extracted.tables:
            notes.append(f"{len(extracted.tables)} tables")
        if extracted.ocr_pages:
            count = len(extracted.ocr_pages)
            notes.append(f"{count} scanned page{'s' if count != 1 else ''} read with OCR")
        messages.append(("success", f"Added **{doc.title}**: " + ", ".join(notes)))
        if extracted.unreadable_pages:
            pages = ", ".join(map(str, extracted.unreadable_pages[:20]))
            messages.append(("warning", f"{doc.title}: scanned pages {pages} could not be read and aren't searchable."))

    # Rerun so the header, sidebar and Search tab see the new documents
    st.session_state["ingest_messages"] = messages
    st.rerun()


def render_library_tab(library: Library, extractor: PDFExtractor, documents: List[Document]) -> None:
    if not extractor.use_ocr:
        if sys.platform == "win32":
            how = ("Install Tesseract (the UB Mannheim build), then re-run `deploy\\windows\\install-service.ps1` "
                   "or set `TESSDATA_PREFIX` to its `tessdata` folder, and restart the app.")
        else:
            how = "Install it with `brew install tesseract` (macOS) or `apt install tesseract-ocr` (Linux) and restart the app."
        st.warning(f"Tesseract OCR was not found, so scanned pages can't be read. {how}")

    outdated = library.outdated_documents()
    if outdated:
        plural = len(outdated) != 1
        with st.container(border=True):
            st.warning(
                f"{len(outdated)} document{'s were' if plural else ' was'} indexed by an older version and "
                f"{'are' if plural else 'is'} missing newer features: tables, figures, cross-references, "
                "military-style formatting and identifier discovery."
            )
            if st.button(f"Re-index {len(outdated)} document{'s' if plural else ''}", type="primary"):
                _reindex(library, extractor, outdated)

    with st.form("add_documents", clear_on_submit=True):
        uploads = st.file_uploader("Add standards (PDF)", type=["pdf"], accept_multiple_files=True)
        submitted = st.form_submit_button("Add to library", type="primary")
    if submitted and uploads:
        _add(library, extractor, uploads)

    for kind, text in st.session_state.pop("ingest_messages", []):
        getattr(st, kind)(text)

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

    if reindex_col.button("Re-index", width="stretch", help="Re-extract from the stored PDF"):
        _reindex(library, extractor, [target])

    with delete_col.popover("Delete…", width="stretch"):
        st.write(f"Remove **{target.title}** and its index from the library? Pins keep their text and citation.")
        if st.button("Delete permanently", type="primary"):
            library.delete_document(target.id)
            st.rerun()

    _identifiers_panel(library, target)


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
