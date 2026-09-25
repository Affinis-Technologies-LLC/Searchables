"""
Discovers identifiers (message labels, field numbers, requirement IDs, part numbers…) without
knowing their format in advance.

Every token that mixes letters and digits, or pairs a short upper-case label with a number, is a
candidate. Candidates are grouped into families by shape ("K7.3" → "K#.#", "FLD 2041" → "FLD#"),
and a family counts as identifiers when it has several distinct values reused across passages.
Measurements, ordinals, clause numbers and structural labels ("Table 12") are never candidates.
"""
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence

from src import config
from src.models import IdentifierFamily, IdentifierOccurrence, TableData, TextBlock

# One token containing both a letter and a digit, parts joined by "." "-" or "_": K7.3, K7.3C1, RQ-0042
_MIXED_TOKEN = re.compile(
    r"(?<![\w.-])(?=[A-Za-z0-9._-]*\d)(?=[A-Za-z0-9._-]*[A-Za-z])[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*(?![\w-])"
)
# A short upper-case label, a space, then a number: FLD 2041
_LABELLED_NUMBER = re.compile(r"(?<![\w.-])([A-Z]{2,6}) (\d{2,6})(?![\w.-])")

# Dot and dash look-alikes that NFKC leaves alone
_DOTS = re.compile(r"[\u2027\u00B7\u2219\u22C5\u30FB\uFF0E]")
_DASHES = re.compile(r"[\u2010\u2011\u2012\u2013\u2212]")

# Words that label document structure, not identifiers ("TABLE 12", "PAGE 40")
_STRUCTURAL = {"TABLE", "TABLES", "FIGURE", "FIGURES", "PAGE", "PAGES", "SECTION", "PARAGRAPH", "PARA",
               "CLAUSE", "ANNEX", "APPENDIX", "NOTE", "NOTES", "EXAMPLE", "STEP", "ITEM", "VOLUME", "PART",
               "CHAPTER", "REV", "VERSION", "EDITION", "CHANGE", "FIG", "TAB", "EQ", "EQUATION"}
# "12mm", "5kg", "2nd", "10s", "1.5V": a number followed by a short unit or ordinal suffix
_MEASUREMENT = re.compile(r"^\d+(?:\.\d+)?[A-Za-z]{1,3}$")
# Appendix clause numbers ("A.2.1") are structure, handled as headings and references
_APPENDIX_CLAUSE = re.compile(r"^[A-Z]\.\d+(?:\.\d+)*$")


def normalize_text(text: str) -> str:
    """
    Look-alike characters to plain ones: full-width letters and digits, "one dot leader" and other
    dot variants, non-breaking and thin spaces (NFKC), and the various dashes to "-". PDFs use these
    freely, and an identifier written with them would otherwise not match.
    """
    text = unicodedata.normalize("NFKC", text)
    return _DASHES.sub("-", _DOTS.sub(".", text))


def identifier_key(value: str) -> str:
    """Matching form: case, spaces, hyphens and underscores ignored ("fld-2041" = "FLD 2041")."""
    return re.sub(r"[\s_-]+", "", normalize_text(value).upper())


def family_of(value: str) -> str:
    """Shape of an identifier: digit runs become "#" ("K7.3C1" → "K#.#C#", "FLD 2041" → "FLD#")."""
    return re.sub(r"\d+", "#", identifier_key(value))


def find_candidates(text: str) -> List[str]:
    """Identifier-like tokens in text, in order of appearance (duplicates kept)."""
    text = normalize_text(text)
    found = []
    for match in _MIXED_TOKEN.finditer(text):
        value = match.group(0)
        if _MEASUREMENT.match(value) or _APPENDIX_CLAUSE.match(value):
            continue
        if re.split(r"[._-]", value.upper())[0].rstrip("0123456789") in _STRUCTURAL:
            continue  # "Table12", "FIG-3"
        found.append((match.start(), value))
    for match in _LABELLED_NUMBER.finditer(text):
        if match.group(1) not in _STRUCTURAL:
            found.append((match.start(), f"{match.group(1)} {match.group(2)}"))
    return [value for _, value in sorted(found)]


def extract_occurrences(blocks: Sequence[TextBlock], tables: Sequence[TableData]) -> List[IdentifierOccurrence]:
    """
    Every candidate in every block, with its role: "heading", "caption" (table/figure captions),
    "table" (a cell; row 0 is the header row) or "text". Table cells are read per row so later
    views can tell which identifiers share a row.
    """
    table_by_block = {t.block_id: t for t in tables}
    occurrences: List[IdentifierOccurrence] = []

    def add(block: TextBlock, text: str, role: str, row: Optional[int] = None) -> None:
        occurrences.extend(
            IdentifierOccurrence(block_id=block.id, value=value, key=identifier_key(value),
                                 family=family_of(value), role=role, row=row)
            for value in find_candidates(text)
        )

    for block in blocks:
        table = table_by_block.get(block.id)
        if table is not None:
            cells = " ".join(" ".join(row) for row in [table.columns, *table.rows])
            caption = block.text[: -len(cells)] if cells and block.text.endswith(cells) else ""
            add(block, caption, "caption")
            for index, row in enumerate([table.columns, *table.rows]):
                add(block, " ".join(row), "table", index)
        elif block.kind == "heading":
            add(block, block.text, "heading")
        elif block.kind == "figure":
            add(block, block.text, "caption")
        else:
            add(block, block.text, "text")
    return occurrences


def summarize_families(occurrences: Iterable[IdentifierOccurrence], doc_id: int) -> List[IdentifierFamily]:
    """
    Per-family statistics, and whether the family is an identifier family by default: several
    distinct values, each family appearing across several passages.
    """
    values: Dict[str, Counter] = defaultdict(Counter)
    passages: Dict[str, set] = defaultdict(set)
    surface: Dict[str, Counter] = defaultdict(Counter)  # How the family is usually written
    for occ in occurrences:
        values[occ.family][occ.value] += 1
        passages[occ.family].add(occ.block_id)
        surface[occ.family][re.sub(r"\d+", "#", occ.value)] += 1

    keys = {family: {identifier_key(v) for v in counts} for family, counts in values.items()}
    enabled = {
        family for family in values
        if len(keys[family]) >= config.IDENTIFIER_MIN_DISTINCT and len(passages[family]) >= config.IDENTIFIER_MIN_PASSAGES
    }
    # Sub-identifiers join their parent's family: if most values extend an accepted identifier
    # ("K3.5C1" extends "K3.5"), they're identifiers too, however few of them there are
    accepted = set().union(*(keys[f] for f in enabled)) if enabled else set()
    for family in set(values) - enabled:
        extending = sum(1 for key in keys[family] if parent_key(key, accepted))
        if extending and extending * 2 >= len(keys[family]):
            enabled.add(family)

    families = [
        IdentifierFamily(
            doc_id=doc_id,
            family=family,
            display=surface[family].most_common(1)[0][0],
            distinct_values=len(keys[family]),
            passages=len(passages[family]),
            examples=", ".join(v for v, _ in counts.most_common(config.IDENTIFIER_EXAMPLES)),
            auto_enabled=family in enabled,
        )
        for family, counts in values.items()
    ]
    return sorted(families, key=lambda f: (-f.auto_enabled, -f.passages))


def parent_key(key: str, known: set) -> Optional[str]:
    """
    The longest known identifier that `key` extends: "K3.5C1" → "K3.5". The next character after
    the parent must not continue its last number ("K3.51" doesn't extend "K3.5").
    """
    for end in range(len(key) - 1, 0, -1):
        candidate = key[:end]
        if candidate in known and not (candidate[-1].isdigit() and key[end].isdigit()):
            return candidate
    return None
