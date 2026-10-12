# ADR-027: Removing the switched-off Streamlit interface

**Status:** proposed 2026-10-11 (draft for agreement; nothing removed). Roadmap step 18. Completes
ADR-007, which superseded Streamlit and kept it "until the new one has been tried".

## Context

The browser front end (ADR-007) has been the interface through every step since; the Streamlit
one (`app.py`, `src/ui/`, `.streamlit/`, 2,495 lines) runs only with `SEARCHABLES_STREAMLIT=1`
and has had no feature since. It still costs:

- **Dependencies** that nothing else needs: `streamlit` and what it pulls in (`pyarrow` 132 MB,
  `pandas` 74 MB, `pydeck`, `altair`, `protobuf`, `tornado`, …), about 280 MB of the 1.6 GB
  environment, and a slice of every `requirements.lock` refresh. `pandas` is used outside
  `src/ui` only by `results_to_dataframe` in `src/utils/formatting.py`, which only the old
  interface calls. `python-docx` stays: the Word export (ADR-005) uses it.
- **A test** (`tests/test_app.py`) that drives the old interface with Streamlit's `AppTest`,
  holding hand counts the new interface's tests already hold.
- **Two code paths** for the same features, so each change to a model or a store must be checked
  against screens nobody opens.
- A distribution (ADR-028) that would ship 280 MB of unused packages.

## Decision

- Delete `app.py`, `src/ui/`, `.streamlit/`, `tests/test_app.py`, and `results_to_dataframe`
  with its `pandas` import. Drop `streamlit` and `pandas` from `requirements.txt`; regenerate
  `requirements.lock`. `deploy/windows/install-service.ps1` stops checking for `app.py` and
  checks for `src/server/__main__.py` instead.
- Keep: `src/utils/formatting.py` for `highlight_values` and `marked_to_html` (used by the server
  and the library); `python-docx`; everything under `src/search`, `src/research`, `src/code`.
- `README.md`, `APP_LAYOUT.md` and `AGENTS.md` lose their Streamlit lines; ADR-007's status
  reads "the Streamlit interface was removed by ADR-027". The ADRs that describe Streamlit-era
  screens (ADR-001 to ADR-006) are history and stay as written.
- Nothing is kept "just in case": the code remains in git history at the tag before the removal.

## Measures

- Before deleting, a test added first asserts that no module outside `src/ui` imports
  `streamlit` or `pandas` (so the deletion can't silently break the server); it stays as a
  guard afterwards.
- The full suite passes without `streamlit` installed (a fresh environment from the new lock).
- The environment's size before and after is recorded (expected: about 280 MB less, on 1.6 GB).
- The server starts and the browser test passes from the fresh environment.

## Consequences

- The repository is one interface. `requirements.lock` shrinks; the Windows install is faster.
- `tests/test_app.py` goes; its assertions (33 → 34 symbols and the like) already live in
  `test_server.py` and `test_browser.py`.
- ADR-028's package is smaller by the same amount.
