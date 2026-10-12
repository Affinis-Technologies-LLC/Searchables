"""
The whole app in a real browser: the built front end (src/server/static) against the server.

Needs Playwright (pip install -r requirements-dev.txt) and Google Chrome; skipped without them.
After changing the front end, build it first: cd web && npm run build
"""
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from src import config
from src.server import app as server

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

PASSWORD = "correct horse battery"


@pytest.fixture
def url(model, monkeypatch):
    if not (server.STATIC / "index.html").exists():
        pytest.skip("The front end hasn't been built (cd web && npm run build).")
    config.AUTH_FILE.unlink(missing_ok=True)
    monkeypatch.setattr(server, "services", server.Services())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    running = uvicorn.Server(uvicorn.Config(server.create_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not running.started:
        assert time.time() < deadline, "the server didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(10)


@pytest.fixture
def page(url):
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        except Exception as e:
            pytest.skip(f"Google Chrome isn't available to Playwright: {e}")
        context = browser.new_context(viewport={"width": 1680, "height": 1000})
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.set_default_timeout(30000)
        expect.set_options(timeout=30000)
        problems = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.goto(url)
        yield page
        browser.close()
        assert problems == [], problems


def test_research_a_document_and_browse_code(page, standard_pdf, tmp_path):
    # First run: create the password
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Confirm password").fill(PASSWORD)
    page.get_by_role("button", name="Create password and continue").click()
    page.wait_for_selector(".activity-bar")

    # Add a PDF, then ask a question: the passage is found, shown on its page and outlined
    pdf = tmp_path / "BROWSER-STD-7.pdf"
    pdf.write_bytes(standard_pdf + b"\n% browser test")
    page.locator(".activity-bar button", has_text="Library").click()
    page.set_input_files("input[type=file]", str(pdf))
    page.wait_for_selector("text=Added BROWSER-STD-7", timeout=120000)

    page.locator(".activity-bar button", has_text="Search").click()
    page.get_by_text("Scope", exact=True).click()
    page.locator(".doc-list label", has_text="BROWSER-STD-7").click()
    box = page.get_by_label("Search the library")
    box.fill("calibration records retained")
    box.press("Enter")
    page.wait_for_selector(".side-pane:not([hidden]) .card.selected")
    first = page.locator(".side-pane:not([hidden]) .card").first
    assert "Calibration records shall be retained" in first.inner_text() and "shall" in first.inner_text()
    page.wait_for_selector(".overlay .hit")
    page.wait_for_selector(".textLayer span")
    assert page.locator(".overlay .passage.selected").count() == 1
    assert page.locator(".tab.on").inner_text().strip() == "BROWSER-STD-7"
    assert "#doc=" in page.url and "page=1" in page.url

    # Copy the passage: its words, then where it's from
    first.get_by_role("button", name="Copy", exact=True).click()
    expect(first.get_by_role("button", name="Copied")).to_be_visible()
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.startswith("Calibration records shall be retained") and copied.endswith("— BROWSER-STD-7, 4.2 Calibration, p. 1")
    page.get_by_label("Cite when copying").uncheck()
    first.get_by_role("button", name="Copy", exact=True).click()
    expect(first.get_by_role("button", name="Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()").endswith("after the equipment is withdrawn.")

    # An identifier: the table row it's in, on page 2, with the table in the inspector
    page.get_by_label("Identifier", exact=True).check()
    box.fill("K3.5")
    box.press("Enter")
    page.wait_for_selector("text=appears in")
    expect(page.locator(".page-input")).to_have_value("2")
    page.locator(".inspector .segments button", has_text="Tables").click()
    page.wait_for_selector(".inspector table.data")
    assert "Item position update" in page.locator(".inspector table.data").first.inner_text()
    page.locator(".inspector").get_by_role("button", name="Copy table").first.click()
    expect(page.locator(".inspector").get_by_role("button", name="Copied").first).to_be_visible()
    cells = page.evaluate("navigator.clipboard.readText()").split("\n")
    assert cells[0].startswith("TABLE 1.") and cells[1] == "Message\tField\tPurpose" and cells[2].split("\t")[0] == "K3.5"

    # The document's contents, and stepping back to where we were
    page.locator(".activity-bar button", has_text="Contents").click()
    page.locator(".outline-row", has_text="Calibration").click()
    expect(page.locator(".page-input")).to_have_value("1")
    page.keyboard.press("Alt+ArrowLeft")
    expect(page.locator(".page-input")).to_have_value("2")

    # Code: add the sample codebase, find a function, follow its usage, and press F12 on the call
    page.locator(".activity-bar button", has_text="Code").click()
    panel = page.locator(".side-pane:not([hidden])")
    if panel.get_by_role("button", name="Add a codebase").count():    # Another test in this run has added one already
        panel.get_by_role("button", name="Add a codebase").click()
    shutil.copytree(Path(__file__).parent / "codebase", tmp_path / "project")   # Its own copy: a folder is listed once
    git = shutil.which("git")
    if git:   # A repository, so Blame has something to show (ADR-026)
        import subprocess
        for args in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "start"]):
            subprocess.run([git, *args], cwd=tmp_path / "project", check=True)
    panel.get_by_placeholder("C:\\Projects").fill(str(tmp_path / "project"))
    panel.get_by_placeholder("Defaults to the folder's name").fill(f"Browser {time.time():.0f}")
    panel.get_by_role("button", name="Add and scan").click()
    page.wait_for_selector("text=/Browser \\d+/", state="attached")
    expect(panel.locator(".panel-head").first).to_contain_text("34 symbols", timeout=60000)
    page.get_by_label("Search the code").fill("fetchUser")
    panel.locator(".card", has_text="fetchUser").first.click()
    page.wait_for_selector(".editor-pane:not([hidden]) .monaco-editor .view-line")
    usage = page.locator(".inspector .code-row.usage")
    usage.first.wait_for()
    assert "UserCard.tsx:7" in usage.first.inner_text()
    usage.first.click()
    expect(page.locator(".tab.on")).to_contain_text("UserCard.tsx")
    call = page.locator(".editor-pane:not([hidden]) .view-line span", has_text="fetchUser").last
    call.wait_for()
    call.click()
    page.keyboard.press("F12")
    expect(page.locator(".tab.on")).to_contain_text("users.ts")
    page.wait_for_selector(".editor-pane:not([hidden]) .line-target")

    # Editing: type into the file, see the unsaved mark, save with the keyboard, and find the new text on disk
    editor = page.locator(".editor-pane:not([hidden]) .monaco-editor")
    editor.locator(".view-lines").click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("// edited in the browser")
    expect(page.locator(".tab.on .unsaved")).to_be_visible()
    started = time.time()
    page.keyboard.press("ControlOrMeta+KeyS")
    expect(page.locator(".tab.on .unsaved")).to_have_count(0, timeout=10000)
    assert time.time() - started < 3, "a save should settle in well under a second"
    saved_file = next(p for p in (tmp_path / "project").rglob("users.ts"))
    assert saved_file.read_text().rstrip().endswith("// edited in the browser")
    # Changed on disk behind the editor: the save is refused and the two versions can be compared
    saved_file.write_text(saved_file.read_text() + "\n// changed outside\n")
    editor.locator(".view-lines").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" and again")
    page.keyboard.press("ControlOrMeta+KeyS")
    expect(page.locator(".notice.error", has_text="changed on disk")).to_be_visible()
    page.locator(".notice.error").get_by_role("button", name="Compare").click()
    page.wait_for_selector(".editor-pane:not([hidden]) .monaco-diff-editor")
    page.get_by_role("button", name="Take the version on disk").click()
    expect(page.locator(".tab.on .unsaved")).to_have_count(0)
    expect(page.locator(".editor-pane:not([hidden]) .view-line", has_text="changed outside")).to_be_visible()
    if git:   # Blame: the committed lines carry a date, the edited ones are marked uncommitted; History lists the commit
        page.locator(".viewer .toolbar").get_by_role("button", name="Blame").click()
        expect(page.locator(".blame-column .blame-line.uncommitted").first).to_be_visible()
        assert "20" in page.locator(".blame-column .blame-line:not(.uncommitted):not(.same)").first.inner_text()
        page.locator(".viewer .toolbar").get_by_role("button", name="Blame").click()
        page.locator(".inspector .segments button", has_text="History").click()
        expect(page.locator(".inspector .code-row", has_text="start")).to_be_visible()

    # Examples as you type: a call on axios shows the codebase's other axios calls; completion lists what's known
    editor.locator(".view-lines").click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("export function ping() { return axios.get(")
    expect(page.locator(".inspector .context-line")).to_contain_text("axios.get", timeout=10000)
    examples = page.locator(".inspector .card.example")
    assert "Same outside API" in examples.first.inner_text() and "fetchUser" in examples.first.inner_text()
    examples.first.get_by_role("button", name="Insert").click()
    expect(page.locator(".editor-pane:not([hidden]) .view-line", has_text="/api/users/${id}")).to_have_count(2)
    page.keyboard.press("Control+End")
    page.keyboard.type(" axios.")
    page.wait_for_selector(".suggest-widget .monaco-list-row", timeout=10000)
    assert "get" in page.locator(".suggest-widget").inner_text()
    page.keyboard.press("Escape")

    # Routes and the calls that reach them
    panel.locator(".segments button", has_text="APIs").click()
    panel.locator(".card", has_text="/api/users/{id}").wait_for()
    assert "← GET /api/users/{}" in panel.locator(".card", has_text="/api/users/{id}").inner_text()

    # Patterns: what's usual in the codebase, each row opening the places it was counted from
    panel.locator(".segments button", has_text="Patterns").click()
    panel.get_by_label("Pattern").select_option("Hotspots")
    hot = panel.locator(".pattern-row").first
    hot.wait_for()
    hot.click()
    panel.locator(".pattern .examples .code-row").first.click()
    expect(page.locator(".tab.on")).to_contain_text(".")

    # Help: F1 opens the page for the view you're in; the ? on a view opens its page; About shows the version
    from src import version
    page.keyboard.press("F1")
    expect(page.locator(".tab.on")).to_contain_text("Help · Code")
    expect(page.locator(".help-page h1")).to_have_text("Code")
    page.locator(".activity-bar button", has_text="Help").click()
    expect(page.locator(".help-page h1")).to_have_text("Help")
    page.locator(".help-page a.link", has_text="Library").first.click()
    expect(page.locator(".help-page h1")).to_have_text("Library")
    page.locator(".side-pane:not([hidden])").get_by_label("Search the help").fill("acronym")
    page.locator(".side-pane:not([hidden]) .tree-row", has_text="Glossary").click()
    expect(page.locator(".help-page h1")).to_have_text("Glossary")
    page.locator(".activity-bar button", has_text="Search").click()
    page.locator(".side-pane:not([hidden]) .help-button").click()
    expect(page.locator(".help-page h1")).to_have_text("Search")
    page.get_by_role("button", name="Account").click()
    page.get_by_role("button", name="About").click()
    about = page.get_by_role("dialog", name="About Searchables")
    expect(about.locator(".about-lines")).to_contain_text(f"Searchables {version.VERSION}")
    expect(about.locator(".about-lines")).to_contain_text("Library:")
    about.get_by_role("button", name="Close").click()

    # A reload keeps the session; signing out ends it
    page.reload()
    page.wait_for_selector(".activity-bar")
    page.get_by_role("button", name="Account").click()
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_selector("text=Sign in")
