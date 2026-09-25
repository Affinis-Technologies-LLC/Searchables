"""Recovers the clause structure of a standard and spots running headers/footers."""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from src import config

# "7", "7.3.2", "A.1" (annex sub-clauses need at least one dot, or "A Pump…" would match)
_NUMBERED_HEADING = re.compile(
    r"^(?P<num>\d{1,2}(?:\.\d{1,3}){0,5}|[A-Z](?:\.\d{1,3}){1,5})\.?\s+(?P<title>\S.*)$"
)
_ANNEX_HEADING = re.compile(
    r"^(?P<word>Annex|ANNEX|Appendix|APPENDIX)\s+(?P<letter>[A-Z])\b[\s:.—–-]*(?P<title>.*)$"
)
_TITLE_CASE_START = re.compile(r"^[A-Z(\"'“]")
# "4.2.1 Transmit rules. The system shall…": a short title ending in a full stop, then body text.
# The full stop must be followed by a space or the end, so dots inside identifiers ("Message K3.5.")
# don't end the title early.
_RUN_IN_END = re.compile(r"\.(?=\s|$)")
# Headings name topics; a numbered sentence with a verbal form is a requirement or list item
_PROVISION_WORDS = re.compile(r"\b(?:shall|should|must|may|will|can)\b", re.IGNORECASE)
TERMS_CLAUSE = re.compile(r"terms|definitions|abbreviations|symbols", re.IGNORECASE)


def _annex_num(match: re.Match) -> str:
    """ "APPENDIX B" → "Appendix B", matching how references to it are normalized."""
    return f"{match.group('word').capitalize()} {match.group('letter')}"


def normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


@dataclass(frozen=True)
class Heading:
    level: int
    num: str
    title: str

    @property
    def label(self) -> str:
        return f"{self.num} {self.title}".strip()


def _level_of(num: str) -> int:
    if num.startswith(("Annex", "Appendix")):
        return 1
    return num.count(".") + 1


def _split_heading_text(text: str) -> Tuple[str, str]:
    """Splits "7.3.2 Design inputs" into ("7.3.2", "Design inputs"); unnumbered titles keep num ""."""
    annex = _ANNEX_HEADING.match(text)
    if annex:
        return _annex_num(annex), annex.group("title").strip()
    match = _NUMBERED_HEADING.match(text)
    if match:
        return match.group("num"), match.group("title").strip().rstrip(".")
    return "", text.strip()


class HeadingDetector:
    """
    Tracks the current clause while blocks are fed in reading order.

    Bookmarks (the PDF outline) are trusted first; numbered-heading patterns fill in the
    deeper clauses that outlines usually omit.
    """

    def __init__(self, toc: List[list]):
        self._toc_by_page: Dict[int, List[Tuple[str, Heading]]] = {}
        for entry in toc:
            level, title, page = entry[0], entry[1], entry[2]
            num, clean_title = _split_heading_text(" ".join(title.split()))
            heading = Heading(level=_level_of(num) if num else level, num=num, title=clean_title)
            self._toc_by_page.setdefault(page, []).append((normalize(title), heading))

        self._stack: List[Heading] = []
        self._top_level: Optional[int] = None

    @property
    def current(self) -> Optional[Heading]:
        return self._stack[-1] if self._stack else None

    @property
    def path(self) -> str:
        return " › ".join(h.label for h in self._stack)

    def feed(self, page: int, text: str) -> Tuple[Optional[Heading], bool]:
        """
        Checks whether a block starts a new clause.
        Returns (heading, is_heading_only): the heading if one starts here, and whether the
        block is nothing but that heading (as opposed to a heading followed by body text).
        """
        normalized = normalize(text)
        for toc_norm, heading in self._toc_by_page.get(page, []):
            if toc_norm and normalized.startswith(toc_norm):
                self._push(heading)
                return heading, len(normalized) <= len(toc_norm) + 2

        first_line = text.split("\n", 1)[0].strip()
        continues = normalize(first_line) != normalized
        matched = self._match_pattern(first_line, continues)
        if matched:
            heading, has_body = matched
            self._push(heading)
            # A run-in heading ("4.1 General. The system…") starts a clause but the block is body text
            return heading, not continues and not has_body
        return None, False

    def _match_pattern(self, line: str, continues: bool = False) -> Optional[Tuple[Heading, bool]]:
        """The heading a line starts, and whether body text follows it on the same line."""
        line = " ".join(line.split())
        if len(line) > config.MAX_HEADING_CHARS and not _RUN_IN_END.search(line):
            return None

        annex = _ANNEX_HEADING.match(line)
        if annex:
            self._top_level = None
            return Heading(level=1, num=_annex_num(annex), title=annex.group("title").strip().rstrip(".")), False

        match = _NUMBERED_HEADING.match(line)
        if not match:
            return None
        num, title = match.group("num"), match.group("title").strip()
        # "Title." and run-in "Title. Body text…" (common in military and government documents):
        # the heading is the short part before the first full stop that's followed by a space
        has_body = False
        end = _RUN_IN_END.search(title)
        if end:
            title, has_body = title[:end.start()].strip(), bool(title[end.end():].strip())
            if _PROVISION_WORDS.search(title) or len(title.split()) > config.MAX_RUN_IN_TITLE_WORDS:
                return None
        elif continues and len(title.split()) > config.MAX_RUN_IN_TITLE_WORDS:
            return None  # A long first line that wraps into more text is a paragraph, not a heading
        # Terms clauses number lowercase entries ("3.1 set pressure"); elsewhere lowercase means "4.2 bar"
        lowercase_ok = "." in num and self._in_terms_clause()
        if (
            not (_TITLE_CASE_START.match(title) or lowercase_ok)
            or title.endswith((".", ",", ";", ":"))
            or len(title.split()) > 15
            or not self._plausible_number(num)
        ):
            return None
        return Heading(level=_level_of(num), num=num, title=title), has_body

    def _in_terms_clause(self) -> bool:
        return bool(self._stack) and bool(TERMS_CLAUSE.search(self._stack[0].title))

    def _plausible_number(self, num: str) -> bool:
        """Clause numbers only move forward; this rejects numbered table rows and list items."""
        top = num.split(".")[0]
        if not top.isdigit():
            return True  # Annex sub-clause such as "A.1"
        top_value = int(top)
        if self._top_level is None:
            return top_value <= 3  # Numbering starts at 0 (Introduction) or 1 (Scope)
        if "." in num:
            return top_value in (self._top_level, self._top_level + 1)
        return self._top_level < top_value <= self._top_level + 3

    def _push(self, heading: Heading) -> None:
        self._stack = [h for h in self._stack if h.level < heading.level] + [heading]
        top = heading.num.split(".")[0]
        if top.isdigit():
            self._top_level = int(top)


def _margin_key(text: str) -> str:
    # Digits vary page to page ("Page 3 of 40"), so they are masked out
    return re.sub(r"\d+", "#", normalize(text))


def find_running_text(pages: Iterable[Tuple[float, List[tuple]]]) -> Set[str]:
    """
    Finds header/footer text repeated across most pages (document IDs, copyright lines).
    Each page is (page_height, raw PyMuPDF blocks). Returns margin keys to drop.
    """
    counts: Counter = Counter()
    page_count = 0
    for height, blocks in pages:
        page_count += 1
        band = height * config.MARGIN_FRACTION
        keys = {
            _margin_key(b[4])
            for b in blocks
            if b[6] == 0 and (b[3] <= band or b[1] >= height - band)
        }
        counts.update(k for k in keys if k)

    if page_count < config.MIN_PAGES_FOR_REPEAT:
        return set()
    threshold = max(2, config.REPEAT_FRACTION * page_count)
    return {key for key, count in counts.items() if count >= threshold}


def is_running_text(block: tuple, height: float, running_keys: Set[str]) -> bool:
    band = height * config.MARGIN_FRACTION
    in_margin = block[3] <= band or block[1] >= height - band
    return in_margin and _margin_key(block[4]) in running_keys
