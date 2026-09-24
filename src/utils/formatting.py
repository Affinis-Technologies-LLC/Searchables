import re
import html
import string
import pandas as pd
from typing import List
from src.models import SearchResult

def apply_term_highlights(text: str, query: str) -> str:
    """Safely escapes text and highlights matched query tokens."""
    terms = {term.strip(string.punctuation) for term in query.split()}
    # Longest first so "liability" wins over "liable" in the alternation
    terms = sorted((t for t in terms if len(t) > 2), key=len, reverse=True)
    if not terms:
        return html.escape(text)

    # Match against the raw text, then escape each piece, so terms never match inside HTML entities
    pattern = re.compile(rf"(?i)(?<!\w)(?:{'|'.join(map(re.escape, terms))})(?!\w)")
    parts: List[str] = []
    last = 0
    for match in pattern.finditer(text):
        parts.append(html.escape(text[last:match.start()]))
        parts.append(f'<mark class="query-hit">{html.escape(match.group())}</mark>')
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)

def marked_to_html(marked: str, start: str, end: str) -> str:
    """Escapes text whose hits are wrapped in start/end marker characters, then turns markers into <mark>."""
    escaped = html.escape(marked)
    return escaped.replace(start, '<mark class="query-hit">').replace(end, "</mark>")

def results_to_dataframe(results: List[SearchResult]) -> pd.DataFrame:
    """Converts search results into a clean tabular format for CSV export."""
    data = [
        {
            "Rank": r.rank,
            "Document": r.doc_title,
            "Clause": r.block.clause,
            "Page": r.block.display_page,
            "Score": round(r.score, 3),
            "Text": r.block.text,
            "Citation": r.citation,
        }
        for r in results
    ]
    return pd.DataFrame(data)