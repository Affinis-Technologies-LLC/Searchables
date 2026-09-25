"""The Compare tab: clause-by-clause differences between two editions."""
import html
import re
from typing import List

import pandas as pd
import streamlit as st

from src import config
from src.models import ClauseDiff, Document
from src.research.compare import provision_change, to_markdown, word_diff_html
from src.search.library import Library
from src.ui.state import show_page
from src.ui.terms import comparison
from src.ui.related_panel import left_pane
from src.ui.viewer import render_viewer

_STATUS_FILTERS = ["Changed", "Added", "Removed", "Renumbered", "Unchanged"]


def _visible(diff: ClauseDiff, statuses: List[str], provisions_only: bool) -> bool:
    shown = diff.status.capitalize() in statuses or (diff.renumbered and "Renumbered" in statuses)
    return shown and (diff.provisions_changed or not provisions_only)


def _guess_editions(documents: List[Document]) -> tuple:
    """Two documents whose titles differ only by year/edition, older first; else the first two."""
    stems = {}
    for doc in documents:
        stems.setdefault(re.sub(r"[\W_]*(?:19|20)\d\d\b.*$", "", doc.title.lower()), []).append(doc)
    for group in stems.values():
        if len(group) >= 2:
            group = sorted(group, key=lambda d: d.title)
            return documents.index(group[-2]), documents.index(group[-1])
    return 0, 1


def render_compare(library: Library, documents: List[Document]) -> None:
    if len(documents) < 2:
        st.info("Add two editions of a standard to the library to compare them clause by clause.")
        return

    older_index, newer_index = _guess_editions(documents)
    old_col, new_col = st.columns(2)
    old = old_col.selectbox("Older edition", documents, index=older_index, format_func=lambda d: d.title,
                            key="compare_old")
    new = new_col.selectbox("Newer edition", documents, index=newer_index, format_func=lambda d: d.title,
                            key="compare_new")
    if old.id == new.id:
        st.warning("Choose two different documents.")
        return

    diffs = comparison(library, old, new)
    counts = {s: sum(d.status == s for d in diffs) for s in ("changed", "added", "removed", "unchanged")}
    metrics = st.columns(5)
    metrics[0].metric("Changed", counts["changed"])
    metrics[1].metric("Added", counts["added"])
    metrics[2].metric("Removed", counts["removed"])
    metrics[3].metric("Renumbered", sum(d.renumbered for d in diffs))
    metrics[4].metric("Requirement changes", sum(d.provisions_changed for d in diffs),
                      help="Clauses whose count of shall / should / may changed")

    with st.container(horizontal=True, vertical_alignment="bottom"):
        statuses = st.pills("Show", _STATUS_FILTERS, selection_mode="multi", default=_STATUS_FILTERS[:4],
                            key="compare_statuses")
        provisions_only = st.toggle("Only shall/should/may changes", key="compare_provisions")
        st.download_button("Markdown", to_markdown(old.title, new.title, diffs), icon=":material/download:",
                           file_name=f"{old.title} vs {new.title}.md", mime="text/markdown")
        st.download_button("CSV", _summary(diffs).to_csv(index=False), icon=":material/table:",
                           file_name=f"{old.title} vs {new.title}.csv", mime="text/csv")

    shown = [d for d in diffs if _visible(d, statuses or _STATUS_FILTERS, provisions_only)]
    list_col, viewer_col = st.columns([2, 3], gap="medium")
    with list_col:
        def clause_list() -> None:
            st.caption(f"{len(shown)} of {len(diffs)} clauses, in the newer edition's order")
            with st.container(height=config.RESULTS_PANE_HEIGHT, border=False):
                for i, diff in enumerate(shown):
                    _clause_card(diff, i, old, new)

        left_pane(library, clause_list)
    with viewer_col:
        with st.container(border=True):
            render_viewer(library, "")


def _clause_card(diff: ClauseDiff, index: int, old: Document, new: Document) -> None:
    ref = diff.new or diff.old
    badges = [f'<span class="badge badge-diff-{diff.status}">{diff.status}</span>']
    if diff.renumbered:
        badges.append(f'<span class="badge badge-metric">was {html.escape(diff.old.num or diff.old.title)}</span>')
    if change := provision_change(diff):
        badges.append(f'<span class="badge badge-requirement">{html.escape(change)}</span>')
    similarity = f'<span class="viewer-count">{diff.similarity:.0%} similar</span>' if diff.status == "changed" else ""

    if diff.status == "changed":
        body = word_diff_html(diff.old.text, diff.new.text) if diff.old.text != diff.new.text else "<em>Title changed only</em>"
    elif diff.status in ("added", "removed"):
        body = html.escape(ref.text) or "<em>Heading only</em>"
    else:
        body = html.escape(ref.text[:300]) + ("…" if len(ref.text) > 300 else "")

    with st.container(border=True):
        st.html(
            f'<div class="result-head">{"".join(badges)}<span class="result-doc">'
            f'{html.escape(f"{ref.num} {ref.title}".strip())}</span>{similarity}</div>'
            f'<div class="result-body diff-body">{body}</div>'
        )
        with st.container(horizontal=True):
            if diff.old:
                st.button(f"Older p. {diff.old.page}", key=f"cmp_old_{index}", on_click=show_page,
                          args=(old.id, diff.old.page, diff.old.bbox), width="content")
            if diff.new:
                st.button(f"Newer p. {diff.new.page}", key=f"cmp_new_{index}", on_click=show_page,
                          args=(new.id, diff.new.page, diff.new.bbox), width="content")


def _summary(diffs: List[ClauseDiff]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Status": d.status,
            "Renumbered": d.renumbered,
            "Old clause": d.old.num if d.old else "",
            "Old title": d.old.title if d.old else "",
            "New clause": d.new.num if d.new else "",
            "New title": d.new.title if d.new else "",
            "Similarity": round(d.similarity, 3),
            "Provision change": provision_change(d),
        }
        for d in diffs
    ])
