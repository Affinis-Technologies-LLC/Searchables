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
        page = browser.new_context(viewport={"width": 1680, "height": 1000}).new_page()
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

    # An identifier: the table row it's in, on page 2, with the table in the inspector
    page.get_by_label("Identifier", exact=True).check()
    box.fill("K3.5")
    box.press("Enter")
    page.wait_for_selector("text=appears in")
    expect(page.locator(".page-input")).to_have_value("2")
    page.locator(".inspector .segments button", has_text="Tables").click()
    page.wait_for_selector(".inspector table.data")
    assert "Track position update" in page.locator(".inspector table.data").first.inner_text()

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
    panel.get_by_placeholder("C:\\Projects").fill(str(tmp_path / "project"))
    panel.get_by_placeholder("Defaults to the folder's name").fill(f"Browser {time.time():.0f}")
    panel.get_by_role("button", name="Add and scan").click()
    page.wait_for_selector("text=/Browser \\d+/", state="attached")
    expect(panel.locator(".panel-head").first).to_contain_text("33 symbols", timeout=60000)
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

    # Routes and the calls that reach them
    panel.locator(".segments button", has_text="APIs").click()
    panel.locator(".card", has_text="/api/users/{id}").wait_for()
    assert "← GET /api/users/{}" in panel.locator(".card", has_text="/api/users/{id}").inner_text()

    # A reload keeps the session; signing out ends it
    page.reload()
    page.wait_for_selector(".activity-bar")
    page.get_by_role("button", name="Account").click()
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_selector("text=Sign in")
