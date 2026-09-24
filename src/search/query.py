"""Turns what a user types into a safe SQLite FTS5 query."""
import re
from typing import List, Optional

_TOKEN = re.compile(r'-?"[^"]*"?\*?|\S+')
_WORD = re.compile(r"\w+")
_OPERATORS = {"AND", "OR", "NOT"}

SYNTAX_HELP = """
| Type | Finds |
|---|---|
| `calibration records` | blocks containing **both** words (any form: *records*, *recorded*) |
| `"shall not exceed"` | the exact phrase |
| `pump OR compressor` | either word |
| `valve -relief` or `valve NOT relief` | *valve* but not *relief* |
| `calib*` | words starting with *calib* |
| `7.3.2`, `AT&T` | treated as a phrase, so punctuation is safe |
"""


def _phrase(words: List[str], prefix: bool = False) -> str:
    return '"' + " ".join(words) + '"' + (" *" if prefix else "")


def build_fts_query(raw: str) -> Optional[str]:
    """
    Supports implicit AND, "exact phrases", OR, NOT / -term and trailing * for prefixes.
    Every term is quoted, so punctuation in the input can never cause an FTS5 syntax error.
    Returns None when nothing searchable remains.
    """
    positives: List[str] = []   # Terms and OR operators, in order
    negatives: List[str] = []
    negate_next = False

    for token in _TOKEN.findall(raw):
        if token in _OPERATORS:
            if token == "NOT":
                negate_next = True
            elif token == "OR" and positives and positives[-1] != "OR":
                positives.append("OR")
            continue

        negate = negate_next or (token.startswith("-") and len(token) > 1)
        negate_next = False
        body = token[1:] if token.startswith("-") else token
        prefix = body.endswith("*")
        words = _WORD.findall(body)
        if not words:
            continue

        term = _phrase(words, prefix=prefix and not body.startswith('"'))
        (negatives if negate else positives).append(term)

    while positives and positives[-1] == "OR":
        positives.pop()
    if not positives:
        return None

    query = " ".join(positives)
    if negatives:
        query = f"({query}) NOT ({' OR '.join(negatives)})"
    return query
