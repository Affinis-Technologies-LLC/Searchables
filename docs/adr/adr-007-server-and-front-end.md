# ADR-007: A local API server and a prebuilt browser front end

**Status:** accepted (supersedes the Streamlit interface, which is switched off and to be removed)

## Context

The first interface was Streamlit, which reruns the whole page on every click and cannot host an
editor or a real PDF viewer. An IDE-like experience needs a front end that keeps state, draws the
real page, and embeds an editor.

## Decision

- **Server:** `src/server`, on Starlette and uvicorn (already dependencies). It answers a JSON API over
  the library, collections, code index and indexer, and serves the front end. Calls take turns on
  the library's single connection; PDFs stream outside that queue. `python -m src.server --check`
  verifies the app can start; the run and service scripts use it.
- **Front end:** `web/`, in TypeScript and React, with **Monaco** (the VS Code editor) for code and
  **PDF.js** for pages, built with Vite into `src/server/static`, which is **committed**, so running
  the app needs no Node.js; only changing the front end does. Dependencies are pinned exactly, and a
  version with a reported vulnerability is not used (`npm audit` must be clean).
- **Layout:** views on the left (Search, Contents, Catalogue, Glossary, Compare, Pins, Code, Library),
  tabs of open documents and files in the middle, an inspector on the right, a status bar below.
  Every view and tab keeps its state; Alt+←/→ step through where you've been; the address bar keeps
  the document, page and search.
- **Sessions:** a random token in an HttpOnly, SameSite=Strict cookie, kept in memory, expiring with
  the idle time-out. Requests that change anything must carry a header a foreign page can't add.
  A content security policy allows only the app's own scripts, styles and workers.
- The editor answers go-to-definition and hover from the code index, not from Monaco's language
  services, which stay unloaded.

## Consequences

- Two languages and a build step; the browser test (`tests/test_browser.py`) drives the built
  front end in Chrome and is the only test of it.
- Served over plain HTTP: binding to anything but `127.0.0.1` sends the password unencrypted, and the
  scripts warn about it.
