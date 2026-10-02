"""Classifies passages by the verbal form ISO/IEC Directives Part 2 uses for each kind of provision."""
import re
from dataclasses import replace
from typing import List, Sequence

from src.models import TextBlock

REQUIREMENT = "requirement"         # shall, shall not (must in some bodies' standards)
RECOMMENDATION = "recommendation"   # should, should not
PERMISSION = "permission"           # may, need not
NOTE = "note"                       # NOTE / EXAMPLE: informative, never binding

_NOTE = re.compile(r"^(?:NOTE|EXAMPLE)\b")
_REQUIREMENT = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)
_RECOMMENDATION = re.compile(r"\bshould\b", re.IGNORECASE)
# Case-sensitive "may" so the month ("May 2020") isn't read as a permission
_PERMISSION = re.compile(r"\b(?:may|need not)\b")
# A list item: "a.", "(b)", "c)", "(1)", "2)", "(iv)" or a bullet, then its text
_LIST_ITEM = re.compile(r"^(?:\(?[a-z]{1,2}[.)]|\(?\d{1,2}\)|\(?[ivx]{1,4}\)|[-–—•·▪○●])\s+\S")


def classify_provision(text: str) -> str:
    """The strongest provision in a passage; a passage with both "shall" and "may" is a requirement."""
    if _NOTE.match(text):
        return NOTE
    if _REQUIREMENT.search(text):
        return REQUIREMENT
    if _RECOMMENDATION.search(text):
        return RECOMMENDATION
    if _PERMISSION.search(text):
        return PERMISSION
    return ""


def inherit_list_provisions(blocks: Sequence[TextBlock]) -> List[TextBlock]:
    """
    Gives list items the provision of their lead-in: after "The terminal shall:", the items
    "a. Transmit…" and "b. Cease…" are requirements although the verbal form is only in the lead-in.
    An item with a verbal form of its own keeps it; the list ends at the first passage that isn't an item.
    """
    result, lead_in = [], ""
    for block in blocks:
        if block.kind == "text" and lead_in and _LIST_ITEM.match(block.text):
            if not block.provision:
                block = replace(block, provision=lead_in)
        elif (block.kind == "text" and block.provision in (REQUIREMENT, RECOMMENDATION, PERMISSION)
              and block.text.rstrip().endswith(":")):
            lead_in = block.provision
        else:
            lead_in = ""
        result.append(block)
    return result
