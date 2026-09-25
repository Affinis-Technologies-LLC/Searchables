"""
Compares two passages already known to be about the same topic, and says how they differ.

The language model only decides *that* two passages are about the same thing. Everything here is a
fixed rule, so each finding can be explained: values and units, the strength of the provision
(shall / should / may), negation, and identifiers.
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from src.extractor.identifiers import family_of
from src.extractor.provisions import PERMISSION, RECOMMENDATION, REQUIREMENT, classify_provision

# Units recognised after a number; plurals and spellings map to one form
_UNITS = {
    "%": "%", "percent": "%",
    "s": "s", "sec": "s", "second": "s", "seconds": "s", "ms": "ms", "millisecond": "ms", "milliseconds": "ms",
    "min": "min", "minute": "min", "minutes": "min", "h": "h", "hr": "h", "hour": "h", "hours": "h",
    "day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month",
    "year": "year", "years": "year", "cycle": "cycle", "cycles": "cycle", "times": "times",
    "bar": "bar", "mbar": "mbar", "pa": "Pa", "kpa": "kPa", "mpa": "MPa", "psi": "psi",
    "mm": "mm", "cm": "cm", "m": "m", "km": "km", "nm": "nm", "ft": "ft", "in": "in",
    "g": "g", "kg": "kg", "t": "t", "lb": "lb", "°c": "°C", "c": "°C", "k": "K", "°f": "°F",
    "v": "V", "kv": "kV", "a": "A", "ma": "mA", "w": "W", "kw": "kW", "hz": "Hz", "khz": "kHz", "mhz": "MHz",
    "ghz": "GHz", "db": "dB", "dbm": "dBm", "bit": "bit", "bits": "bit", "byte": "byte", "bytes": "byte",
    "kbps": "kbps", "mbps": "Mbps",
}
_QUANTITY = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(%|°[CFcf]|[A-Za-z]+)\b")
_STRENGTH = {REQUIREMENT: 3, RECOMMENDATION: 2, PERMISSION: 1}
_WORD_FOR = {REQUIREMENT: "shall", RECOMMENDATION: "should", PERMISSION: "may"}
_NEGATED = re.compile(r"\b(?:shall|must|should)\s+not\b|\bshall\s*n[o']t\b", re.IGNORECASE)
_POSITIVE = re.compile(r"\b(?:shall|must|should)\b(?!\s+not)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    label: str                  # "Different value", "Weaker requirement", …
    detail: str = ""            # "12 months → 6 months"


def quantities(text: str) -> Dict[str, Set[str]]:
    """Unit → the values given in that unit: "an interval of 12 months" → {"month": {"12"}}."""
    found: Dict[str, Set[str]] = defaultdict(set)
    for value, unit in _QUANTITY.findall(text):
        normal = _UNITS.get(unit.lower())
        if normal:
            found[normal].add(value.replace(",", "."))
    return found


_COUNTED_UNITS = {"day", "week", "month", "year", "cycle", "bit", "byte"}  # Written "12 months", not "12 month"


def _fmt(values: Iterable[str], unit: str) -> str:
    ordered = sorted(values, key=lambda v: float(v))
    joined = ", ".join(ordered)
    if unit == "%":
        return f"{joined}%"
    plural = unit in _COUNTED_UNITS and not (len(ordered) == 1 and float(ordered[0]) == 1)
    return f"{joined} {unit}{'s' if plural else ''}"


def assess(pairs: Sequence[Tuple[str, str, float]], focus_identifiers: Sequence[str] = (),
           other_identifiers: Sequence[str] = (), corresponding: float = 0.86,
           same_content: float = 0.97) -> Tuple[List[Finding], Tuple[str, str]]:
    """
    How another passage differs from the focus passage, both about the same topic. `pairs` are the
    focus's sentences each matched with their closest sentence in the other passage (best first);
    pairs at least `corresponding` similar are taken to say the same kind of thing, and are compared
    for values, provision strength and negation. Returns the findings and the sentence pair to show.
    """
    findings: List[Finding] = []
    shown = pairs[0][:2]
    matched = [p for p in pairs if p[2] >= corresponding]

    for ours, theirs, _ in matched:
        found: List[Finding] = []
        # Values: the same unit with different numbers ("12 months" vs "6 months")
        mine, yours = quantities(ours), quantities(theirs)
        for unit in sorted(set(mine) & set(yours)):
            if mine[unit] != yours[unit]:
                found.append(Finding("Different value", f"{_fmt(mine[unit], unit)} → {_fmt(yours[unit], unit)}"))
        # Provision strength of the corresponding sentences: shall > should > may
        a, b = classify_provision(ours), classify_provision(theirs)
        if _STRENGTH.get(a) and _STRENGTH.get(b) and a != b:
            label = "Stronger requirement" if _STRENGTH[b] > _STRENGTH[a] else "Weaker requirement"
            found.append(Finding(label, f"{_WORD_FOR[a]} → {_WORD_FOR[b]}"))
        # Negation: one says "shall not" where the other says "shall"
        ours_neg, theirs_neg = bool(_NEGATED.search(ours)), bool(_NEGATED.search(theirs))
        if ours_neg != theirs_neg and _POSITIVE.search(theirs if ours_neg else ours):
            found.append(Finding("Possible conflict", "one says “shall not” where the other says “shall”"))
        if found:
            if not findings:
                shown = (ours, theirs)  # Show the first sentences that differ
            findings.extend(f for f in found if f not in findings)

    # Identifiers of the same kind that differ ("FLD 2041" vs "FLD 2042"), as one finding
    by_family: Dict[str, Tuple[Set[str], Set[str]]] = defaultdict(lambda: (set(), set()))
    for value in focus_identifiers:
        by_family[family_of(value)][0].add(value)
    for value in other_identifiers:
        by_family[family_of(value)][1].add(value)
    only_mine, only_yours = [], []
    for family, (mine_ids, yours_ids) in sorted(by_family.items()):
        if mine_ids and yours_ids and mine_ids != yours_ids:
            only_mine += sorted(mine_ids - yours_ids)
            only_yours += sorted(yours_ids - mine_ids)
    if only_mine or only_yours:
        findings.append(Finding("Different identifiers",
                                f"{', '.join(only_mine[:3]) or '—'} → {', '.join(only_yours[:3]) or '—'}"))

    # Same content: every sentence has a near-identical counterpart and nothing differs
    if not findings and pairs and all(p[2] >= same_content for p in pairs):
        findings.append(Finding("Same content"))
    return findings, shown
