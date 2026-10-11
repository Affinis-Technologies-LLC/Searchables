"""
The app's version (ADR-016): the VERSION file at the top of the repository, plus the commit the
checkout is at, read from .git (no command is run). A release is a bump of the file, a commit and a
tag of the same number.
"""
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"


def _commit() -> str:
    """The short commit from .git/HEAD, following a branch reference; "" without a checkout."""
    git = ROOT / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            ref_file = git / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:9]
            packed = git / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0][:9]
            return ""
        return head[:9]
    except OSError:
        return ""


def describe() -> Dict[str, object]:
    return {"version": VERSION, "commit": _commit(), "checkout": (ROOT / ".git").exists()}
