"""Reads defined terms from a standard's "Terms and definitions" clause and finds them in text."""
import re
from collections import OrderedDict
from typing import Dict, List, Sequence

from src.extractor.structure import TERMS_CLAUSE
from src.models import Term, TextBlock

_NOTE_TO_ENTRY = re.compile(r"^(?:Note \d+ to entry|NOTE|EXAMPLE|\[SOURCE)")


def build_glossary(blocks: Sequence[TextBlock]) -> List[Term]:
    """
    Terms are the numbered entries under a top-level clause titled like "Terms and definitions"
    ("3.1 set pressure", then its definition). Entries with no definition text are category
    headings ("3.1 General terms") and are skipped. Works on already-indexed documents.
    """
    terms_clauses = {
        b.clause_num for b in blocks
        if b.kind == "heading" and b.clause_num and "." not in b.clause_num and TERMS_CLAUSE.search(b.clause_title)
    }
    if not terms_clauses:
        return []

    entries: Dict[str, List[TextBlock]] = OrderedDict()
    for block in blocks:
        top = block.clause_num.split(".")[0]
        if top in terms_clauses and "." in block.clause_num:
            entries.setdefault(block.clause_num, []).append(block)

    glossary = []
    for num, entry in entries.items():
        heading = next((b for b in entry if b.kind == "heading"), entry[0])
        title = entry[0].clause_title
        parts = []
        for block in entry:
            if block.kind != "text":
                continue
            text = block.text
            # A heading can share a block with the start of its definition ("3.1 set pressure predetermined…")
            prefix = f"{num} {title}"
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
            if text and not _NOTE_TO_ENTRY.match(text):
                parts.append(text)
        if not parts:
            continue
        # Synonyms share an entry separated by ";" (commas occur inside term names)
        names = [n.strip() for n in title.split(";") if n.strip()]
        glossary.append(Term(
            term=names[0], synonyms=tuple(names[1:]), clause_num=num, definition=" ".join(parts),
            doc_id=heading.doc_id, page=heading.page, page_label=heading.display_page, bbox=heading.bbox,
        ))
    return glossary


def _term_pattern(name: str) -> re.Pattern:
    words = r"\s+".join(map(re.escape, name.split()))
    return re.compile(rf"(?<![\w-]){words}(?:s|es)?(?![\w-])", re.IGNORECASE)


def terms_in_text(glossary: Sequence[Term], text: str) -> List[Term]:
    """Defined terms used in `text`, longest names first so "relief valve" beats "valve"."""
    found, taken = [], []
    for term in sorted(glossary, key=lambda t: -max(len(n) for n in t.names)):
        for name in term.names:
            match = _term_pattern(name).search(text)
            # Skip a shorter term found inside a longer one already matched ("valve" in "relief valve")
            if match and not any(s <= match.start() and match.end() <= e for s, e in taken):
                found.append(term)
                taken.append(match.span())
                break
    return found
