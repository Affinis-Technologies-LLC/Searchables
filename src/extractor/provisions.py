"""Classifies passages by the verbal form ISO/IEC Directives Part 2 uses for each kind of provision."""
import re

REQUIREMENT = "requirement"         # shall, shall not (must in some bodies' standards)
RECOMMENDATION = "recommendation"   # should, should not
PERMISSION = "permission"           # may, need not
NOTE = "note"                       # NOTE / EXAMPLE: informative, never binding

_NOTE = re.compile(r"^(?:NOTE|EXAMPLE)\b")
_REQUIREMENT = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)
_RECOMMENDATION = re.compile(r"\bshould\b", re.IGNORECASE)
# Case-sensitive "may" so the month ("May 2020") isn't read as a permission
_PERMISSION = re.compile(r"\b(?:may|need not)\b")


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
