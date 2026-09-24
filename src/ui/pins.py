"""Pin buttons shared by search results and the viewer."""
from dataclasses import dataclass, field
from typing import Set

import streamlit as st

from src.models import TextBlock
from src.research.collections import CollectionStore, pin_key
from src.search.library import Library
from src.ui.tables import table_payload


@dataclass
class PinContext:
    library: Library
    store: CollectionStore
    collection_id: int
    query: str = ""
    pinned: Set[str] = field(default_factory=set)   # pin_key()s already in the active collection


def _toggle_pin(ctx: PinContext, block: TextBlock, doc_title: str, citation: str) -> None:
    if pin_key(block) in ctx.pinned:
        ctx.store.remove_pin_for(ctx.collection_id, block)
    else:
        table = table_payload(ctx.library, block) if block.kind == "table" else None
        ctx.store.add_pin(ctx.collection_id, block, doc_title, citation, ctx.query, table)


def pin_button(ctx: PinContext, block: TextBlock, doc_title: str, citation: str, key: str) -> None:
    pinned = pin_key(block) in ctx.pinned
    st.button(
        "Pinned ✓" if pinned else "Pin",
        key=key,
        icon=None if pinned else ":material/push_pin:",
        help="Remove from the collection" if pinned else "Save to the active collection",
        on_click=_toggle_pin,
        args=(ctx, block, doc_title, citation),
        width="content",
    )
