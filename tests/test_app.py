"""The app itself, run without a browser: set-up, sign-in, and a search over an indexed document."""
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config
from src.code.store import CodeStore
from src.research.collections import CollectionStore
from src.research.export import to_markdown
from src.search.indexer import ADD, Indexer
from src.search.library import Library

PASSWORD = "correct horse battery"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("SEARCHABLES_STREAMLIT", "1")   # It's switched off otherwise, in favour of src/server
    config.AUTH_FILE.unlink(missing_ok=True)   # Each test starts at the set-up page; the library is shared
    test = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    yield test.run()


def test_set_up_then_search(app, standard_pdf, model):
    assert app.title[0].value == "Searchables" and "Create a password" in app.subheader[0].value
    app.text_input[0].set_value(PASSWORD)
    app.text_input[1].set_value(PASSWORD)
    app.button[0].click().run()
    assert not app.exception and app.title[0].value == "Standards Search"
    assert config.AUTH_FILE.exists()

    indexer = Indexer(library_factory=Library)
    indexer.submit(ADD, "ACME-STD-1234.pdf", file_bytes=standard_pdf)
    while indexer.active():
        time.sleep(0.05)
    app.run()
    app.text_input(key="query_input").set_value("how long must calibration records be kept").run()
    assert not app.exception
    assert any("matching passages" in caption.value for caption in app.caption)


def test_switched_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("SEARCHABLES_STREAMLIT", raising=False)
    off = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60).run()
    assert not off.exception and off.title[0].value == "Searchables has a new interface" and not off.text_input


def test_wrong_password_is_refused(app):
    app.text_input[0].set_value(PASSWORD)
    app.text_input[1].set_value(PASSWORD)
    app.button[0].click().run()
    app.session_state["authenticated"] = False       # Signed out
    app.run()
    app.text_input[0].set_value("not the password").run()
    app.button[0].click().run()
    assert "Incorrect password" in app.error[0].value and app.title[0].value == "Searchables"


def test_code_tab(app):
    app.text_input[0].set_value(PASSWORD)
    app.text_input[1].set_value(PASSWORD)
    app.button[0].click().run()
    library = Library()
    for codebase in CodeStore(library.conn).list_codebases():      # Left by an earlier run in this session
        CodeStore(library.conn).remove(codebase.id)
    store = CodeStore(library.conn)
    codebase = store.add(str(Path(__file__).parent / "codebase"), "Demo")
    store.index(codebase.id)

    def run(action=None):
        """AppTest doesn't keep the chosen tab between runs, so it's chosen again each time."""
        app.session_state["side_tab"] = "Code"
        return (action or app).run()

    run()
    assert not app.exception and app.title[0].value == "Code Search"
    assert any("33 symbols" in c.value for c in app.caption)
    run(app.text_input(key="code_query").set_value("fetchUser"))
    run(next(b for b in app.button if b.label == "Explore").click())
    assert not app.exception
    assert app.session_state["code_view"] == "Symbol" and app.session_state["code_line"] == 5
    assert any(b.label.endswith("UserCard.tsx:7") for b in app.button)                 # Its usage, linked

    run(next(b for b in app.button if b.label == "Pin").click())
    pins = CollectionStore(library.conn).pins(app.session_state["active_collection"])
    assert pins[-1].kind == "code" and pins[-1].citation == "Demo, frontend/src/api/users.ts:5"
    assert "```\nexport async function fetchUser" in to_markdown("c", pins)

    for view in ("Dependencies", "APIs", "Files"):
        app.session_state["code_view_input"] = view
        run()
        assert not app.exception, view

    app.session_state["side_tab"] = "Documents"                                        # Back to the documents
    app.run()
    assert not app.exception and app.title[0].value == "Standards Search"
