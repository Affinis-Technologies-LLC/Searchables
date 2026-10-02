"""Reads defined terms from a standard's "Terms and definitions" clause and finds them in text."""
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence

from src.extractor.structure import ACRONYMS_CLAUSE, TERMS_CLAUSE
from src.models import TableData, Term, TextBlock

_NOTE_TO_ENTRY = re.compile(r"^(?:Note \d+ to entry|NOTE|EXAMPLE|\[SOURCE)")
# Sub-clauses that introduce lists or groups rather than define a term ("3.1 Acronyms", "3.1 General")
_LIST_ENTRY = re.compile(r"^(?:acronyms?|abbreviations?|general(?: terms)?)\b", re.IGNORECASE)


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
        if TERMS_CLAUSE.search(title) or _LIST_ENTRY.search(title):
            continue  # "3.1 Acronyms." and similar introduce lists, not a defined term
        parts = []
        for block in entry:
            if block.kind != "text":
                continue
            text = block.text
            # A heading can share a block with the start of its definition ("3.1 set pressure predetermined…")
            prefix = f"{num} {title}"
            if text.startswith(prefix):
                # Run-in entries ("3.1 Term. Definition…") leave the title's full stop behind
                text = text[len(prefix):].lstrip(" .:—–-").strip()
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


_ACRONYM = re.compile(r"^[A-Z][A-Z0-9&/.-]{1,11}$")
_SEPARATOR = re.compile(r"^[-–—:=]+$")


def build_acronyms(blocks: Sequence[TextBlock], tables: Optional[Dict[int, TableData]] = None) -> List[Term]:
    """
    Acronyms and what they stand for, from clauses titled "Acronyms" or "Abbreviations". Entries are
    read however the list was laid out: a table's first two columns, lines of "SPLR Precise
    Participant Location and Identification", or the acronyms and their meanings as two columns of text.
    """
    found: Dict[str, Term] = {}

    def add(acronym: str, meaning: str, block: TextBlock) -> None:
        meaning = meaning.strip(" -–—:=.")
        if _ACRONYM.match(acronym) and meaning and acronym not in found:
            found[acronym] = Term(term=acronym, synonyms=(), clause_num=block.clause_num, definition=meaning,
                                  doc_id=block.doc_id, page=block.page, page_label=block.display_page,
                                  bbox=block.bbox, acronym=True)

    listed = [b for b in blocks if ACRONYMS_CLAUSE.search(b.clause_title) and b.kind in ("text", "table")]
    skip = False
    for i, block in enumerate(listed):
        if skip:
            skip = False
            continue
        table = (tables or {}).get(block.id)
        if table is not None:
            for row in [table.columns, *table.rows]:
                if len(row) >= 2:
                    add(row[0].strip(), row[1], block)
            continue
        lines = [line for line in block.text.split("\n") if line.strip()]
        following = listed[i + 1].text.split("\n") if i + 1 < len(listed) and listed[i + 1].kind == "text" else []
        if lines and all(_ACRONYM.match(line.strip()) for line in lines) and len(following) == len(lines):
            for acronym, meaning in zip(lines, following):   # Two columns of text: acronyms, then meanings
                add(acronym.strip(), meaning, block)
            skip = True
            continue
        last = None
        for line in lines:
            words = line.split()
            rest = words[2:] if len(words) > 2 and _SEPARATOR.match(words[1]) else words[1:]
            if _ACRONYM.match(words[0]) and rest and rest[0][:1].isupper():
                add(words[0], " ".join(rest), block)
                last = words[0]
            elif last in found and not line[:1].isdigit():   # A meaning that wrapped onto the next line
                found[last] = Term(**{**found[last].__dict__, "definition": f"{found[last].definition} {line.strip()}"})
    return sorted(found.values(), key=lambda t: t.term)


def expand_acronyms(query: str, acronyms: Dict[str, str]) -> List[tuple]:
    """
    (acronym, meaning) for the acronyms a search uses, either way round: typed as the acronym (in
    capitals, or in any case when it's four letters or more), or spelled out.
    """
    words = set(re.findall(r"[\w&/.-]+", query))
    lowered = {w.lower() for w in words if len(w) >= 4}
    spelled = " ".join(query.lower().split())
    return [(acronym, meaning) for acronym, meaning in acronyms.items()
            if acronym in words or acronym.lower() in lowered or meaning.lower() in spelled]


def _term_pattern(name: str, exact: bool = False) -> re.Pattern:
    if exact:   # An acronym: as written, so "IT" isn't found in "it"
        return re.compile(rf"(?<![\w-]){re.escape(name)}(?:s)?(?![\w-])")
    words = r"\s+".join(map(re.escape, name.split()))
    return re.compile(rf"(?<![\w-]){words}(?:s|es)?(?![\w-])", re.IGNORECASE)


def terms_in_text(glossary: Sequence[Term], text: str) -> List[Term]:
    """Defined terms used in `text`, longest names first so "relief valve" beats "valve"."""
    found, taken = [], []
    for term in sorted(glossary, key=lambda t: -max(len(n) for n in t.names)):
        for name in term.names:
            match = _term_pattern(name, term.acronym).search(text)
            # Skip a shorter term found inside a longer one already matched ("valve" in "relief valve")
            if match and not any(s <= match.start() and match.end() <= e for s, e in taken):
                found.append(term)
                taken.append(match.span())
                break
    return found
