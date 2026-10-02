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
# A short upper-case label, a space, then a number: FLD 2041 (a full stop ending the sentence may follow)
_LABELLED_NUMBER = re.compile(r"(?<![\w.-])([A-Z]{2,6}) (\d{2,6})(?![\w-])(?!\.\w)")

# A short label, a space, then a dotted number: "M 12.6" is the identifier "M12.6" written with a space
_SPACED_LABEL = re.compile(r"(?<![\w.-])([A-Z]{1,3}) (\d{1,3}\.\d{1,3}[A-Z0-9]*)(?![\w-])(?!\.\w)")
# Two labels numbered together name one thing: "GRP/ITM 1620/003", "GRP 281/ITM 001", "GRP 281, ITM 001"
_PAIR_JOINT = re.compile(r"(?<![\w.-])([A-Z]{2,6})\s?/\s?([A-Z]{2,6}) (\d{1,6})\s?/\s?(\d{1,6})(?![\w-])(?!\.\w)")
_PAIR_SPLIT = re.compile(r"(?<![\w.-])([A-Z]{2,6}) (\d{1,6})\s?[/,]\s?([A-Z]{2,6}) (\d{1,6})(?![\w-])(?!\.\w)")
_PAIR_KEY = re.compile(r"^([A-Z]+)/([A-Z]+)(\d+)/(\d+)$")
_PAIR_HEADER = re.compile(r"^([A-Z]{2,6})\s?/\s?([A-Z]{2,6})\b")
_PAIR_CELL = re.compile(r"^(\d{1,6})\s?/\s?(\d{1,6})$")

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
    taken: List[tuple] = []   # Spans already read as a pair or a spaced label: their parts aren't identifiers of their own
    for pattern in (_PAIR_JOINT, _PAIR_SPLIT):
        for match in pattern.finditer(text):
            first, second = (1, 2) if pattern is _PAIR_JOINT else (1, 3)
            numbers = (3, 4) if pattern is _PAIR_JOINT else (2, 4)
            labels = (match.group(first), match.group(second))
            if set(labels) & _STRUCTURAL or any(s <= match.start() < e for s, e in taken):
                continue
            taken.append(match.span())
            found.append((match.start(), pair_value(*labels, match.group(numbers[0]), match.group(numbers[1]))))
            found.append((match.start(), f"{labels[0]} {match.group(numbers[0])}"))   # Also findable by its first part
    for match in _SPACED_LABEL.finditer(text):
        if match.group(1) not in _STRUCTURAL and not any(s <= match.start() < e for s, e in taken):
            taken.append(match.span())
            found.append((match.start(), match.group(0)))
    for match in _MIXED_TOKEN.finditer(text):
        value = match.group(0)
        if _MEASUREMENT.match(value) or _APPENDIX_CLAUSE.match(value) or any(s <= match.start() < e for s, e in taken):
            continue
        if re.split(r"[._-]", value.upper())[0].rstrip("0123456789") in _STRUCTURAL:
            continue  # "Table12", "FIG-3"
        found.append((match.start(), value))
    for match in _LABELLED_NUMBER.finditer(text):
        if match.group(1) not in _STRUCTURAL and not any(s <= match.start() < e for s, e in taken):
            found.append((match.start(), f"{match.group(1)} {match.group(2)}"))
    return [value for _, value in sorted(found, key=lambda item: item[0])]


def pair_value(first: str, second: str, number: str, other: str) -> str:
    """How a pair of numbered labels is written, whichever way the text put it: "GRP/ITM 281/001"."""
    return f"{first}/{second} {number}/{other}"


def labelled_cells(columns: Sequence[str], row: Sequence[str], labels: set, pairs: set) -> List[str]:
    """
    Identifiers a table row gives through its column headings: a bare number under a heading that's
    used as an identifier label elsewhere in the document ("GRP" over "281"), and number pairs under
    a joint heading ("GRP/ITM" over "281/001") or under two neighbouring headings known as a pair.
    """
    found: List[str] = []
    heads = [normalize_text(c).upper().strip() for c in columns]
    cells = [normalize_text(c).strip() for c in row]
    for i, (head, cell) in enumerate(zip(heads, cells)):
        joint, split = _PAIR_HEADER.match(head), _PAIR_CELL.match(cell)
        if joint and split and not set(joint.groups()) & _STRUCTURAL:
            found += [pair_value(joint.group(1), joint.group(2), *split.groups()), f"{joint.group(1)} {split.group(1)}"]
        elif head in labels and re.fullmatch(r"\d{1,6}", cell):
            found.append(f"{head} {cell}")
            following = heads[i + 1] if i + 1 < len(heads) else ""
            if (head, following) in pairs and i + 1 < len(cells) and re.fullmatch(r"\d{1,6}", cells[i + 1]):
                found.append(pair_value(head, following, cell, cells[i + 1]))
    return found


def extract_occurrences(blocks: Sequence[TextBlock], tables: Sequence[TableData]) -> List[IdentifierOccurrence]:
    """
    Every candidate in every block, with its role: "heading", "caption" (table/figure captions),
    "table" (a cell; row 0 is the header row) or "text". Table cells are read per row so later
    views can tell which identifiers share a row.
    """
    table_by_block = {t.block_id: t for t in tables}
    occurrences: List[IdentifierOccurrence] = []
    # Labels the document numbers things by ("GRP 281"), and pairs of them: these give meaning to bare
    # numbers under the same headings in tables
    labels, pairs = set(), set()
    for block in blocks:
        text = normalize_text(block.text)
        labels.update(m.group(1) for m in _LABELLED_NUMBER.finditer(text) if m.group(1) not in _STRUCTURAL)
        for pattern, second in ((_PAIR_JOINT, 2), (_PAIR_SPLIT, 3)):
            for m in pattern.finditer(text):
                labels.add(m.group(1))
                pairs.add((m.group(1), m.group(second)))

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
                if index:
                    occurrences.extend(
                        IdentifierOccurrence(block_id=block.id, value=value, key=identifier_key(value),
                                             family=family_of(value), role="table", row=index)
                        for value in labelled_cells(table.columns, row, labels, pairs)
                    )
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
    pair = _PAIR_KEY.match(key)   # "GRP/ITM 281/001" belongs to "GRP 281"
    if pair and pair.group(1) + pair.group(3) in known:
        return pair.group(1) + pair.group(3)
    return None
