"""Turns stored tables (and their continuations) into DataFrames, HTML and pin payloads."""
import html
from typing import List, Optional, Tuple

import pandas as pd

from src.models import TableData, TextBlock
from src.search.library import Library
from src.utils.formatting import highlight_values


def unique_columns(names: List[str]) -> List[str]:
    """Blank or repeated header cells (merged cells) would break the table widget."""
    seen: dict = {}
    unique = []
    for i, name in enumerate(names):
        name = name or f"Column {i + 1}"
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return unique


def table_caption(block: TextBlock, part: TableData) -> str:
    """The block's text is the caption followed by every cell; strip the cells to recover the caption."""
    cells = " ".join(" ".join(row) for row in [part.columns, *part.rows])
    return block.text[: -len(cells)].strip() if cells and block.text.endswith(cells) else ""


def table_frame(library: Library, block: TextBlock) -> Tuple[pd.DataFrame, List[int]]:
    """A table and its continuations as one DataFrame, plus the pages it spans."""
    parts = library.table_parts(block)
    columns = unique_columns(parts[0][1].columns)
    rows = [
        (row + [""] * len(columns))[:len(columns)]  # Continuations can have ragged rows
        for _, data in parts for row in data.rows
    ]
    return pd.DataFrame(rows, columns=columns), sorted({b.page for b, _ in parts})


def table_payload(library: Library, block: TextBlock) -> Optional[dict]:
    """What a pin keeps of a table: its caption and the joined grid."""
    parts = library.table_parts(block)
    if not parts:
        return None
    frame, _ = table_frame(library, block)
    return {
        "caption": table_caption(*parts[0]),
        "columns": list(frame.columns),
        "rows": frame.values.tolist(),
    }


def table_html(library: Library, block: TextBlock) -> str:
    """This page's part of a table as a small HTML table."""
    part = next((data for b, data in library.table_parts(block) if b.id == block.id), None)
    if part is None:
        return html.escape(block.text)
    head = "".join(f"<th>{html.escape(c)}</th>" for c in part.columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in part.rows)
    return (f'<div class="context-caption">{html.escape(table_caption(block, part))}</div>'
            f'<table class="page-table"><tr>{head}</tr>{body}</table>')


def table_rows_html(library: Library, block: TextBlock, rows, values) -> str:
    """The caption, header and just the given rows of a table (row 0 = header), with values highlighted."""
    part = next((data for b, data in library.table_parts(block) if b.id == block.id), None)
    if part is None:
        return highlight_values(block.text, values)
    head = "".join(f"<th>{highlight_values(c, values)}</th>" for c in part.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{highlight_values(c, values)}</td>" for c in part.rows[r - 1]) + "</tr>"
        for r in rows if 0 < r <= len(part.rows)
    )
    return (f'<div class="context-caption">{html.escape(table_caption(block, part))}</div>'
            f'<table class="page-table"><tr>{head}</tr>{body}</table>')
