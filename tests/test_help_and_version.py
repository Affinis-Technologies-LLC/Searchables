"""A version the app can show, an About, and help inside the app (ADR-016)."""
import json
import re
from pathlib import Path

from src import version

ROOT = Path(__file__).parent.parent
HELP = ROOT / "docs" / "help"


def test_the_version_comes_from_the_version_file():
    assert version.VERSION == (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.VERSION)
    about = version.describe()
    assert about["version"] == version.VERSION
    assert about["commit"] == "" or re.fullmatch(r"[0-9a-f]{7,12}", about["commit"])   # From .git/HEAD, when there is one
    assert about["checkout"] == ((ROOT / ".git").exists())


def activities():
    text = (ROOT / "web/src/shell/ActivityBar.tsx").read_text()
    return re.findall(r'id: "([a-z]+)"', text)


def test_every_activity_has_a_help_page_and_links_between_pages_resolve():
    ids = activities()
    assert "help" in ids and len(ids) >= 9
    pages = {p.stem: p.read_text() for p in HELP.glob("*.md")}
    missing = [a for a in ids if a not in pages]
    assert not missing, f"no help page for {missing}"
    for name, text in pages.items():
        assert text.startswith("# "), f"{name}.md must start with a heading"
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith("app:"):
                assert target[4:].split("/")[0] in ids, f"{name}.md links to an unknown view {target}"
            elif target.endswith(".md"):
                assert target[:-3] in pages, f"{name}.md links to a missing page {target}"
            else:
                assert target.startswith("#"), f"{name}.md links outside the help ({target}); help must work offline"


def test_help_pages_say_what_the_app_never_does():
    text = (HELP / "help.md").read_text().lower()
    for promise in ("no ai", "nothing leaves", "nothing of the codebase is run", "never pushes"):
        assert promise in text, promise


def test_the_front_end_bundles_the_version_and_help(tmp_path):
    built = ROOT / "src/server/static"
    if not (built / "index.html").exists():
        return
    bundle = "".join(p.read_text(errors="replace") for p in built.glob("assets/*.js"))
    assert version.VERSION in bundle
    heading = (HELP / "search.md").read_text().splitlines()[0][2:]
    assert heading in bundle
