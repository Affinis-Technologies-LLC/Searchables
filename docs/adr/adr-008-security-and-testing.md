# ADR-008: Restricted material, and tests that protect the code

**Status:** accepted

## Context

The documents are licensed and distribution-restricted, and the subject matter should not be
identifiable from the repository. The code changes often and in large steps.

## Decision

### Material

- The library folder is private to the user's account (`chmod 700`; on Windows the install script
  limits it to administrators and the service account). Files in it are not encrypted; disk
  encryption is the user's.
- A password protects the app; its hash is scrypt with a salt; wrong attempts lock sign-in briefly.
- A document's distribution statement is found when it's indexed, shown with the document, and
  carried into every export with each extract from it.
- **The repository names no specific standard and uses none of its vocabulary**: not in code,
  comments, docs, tests, fixtures or commit messages. Test fixtures use made-up names
  (`XYZ-STD-9999`, messages `M3.2`, pairs `GRP/ITM 281/001`, acronyms `SPLR`, `RN`, `NU`), and no
  real document is ever committed.
- Python packages are installed from `requirements.lock`, pinned by version and hash for every
  platform; npm packages from `package-lock.json`.

### Tests

- Tests build their own PDFs and codebases and use a stand-in for the embedding model, so they
  need neither the user's documents nor the downloaded model, never touch the user's library, and
  never load (or download) the real model.
- Coverage of `src/` is about 81% (excluding the switched-off Streamlit screens). The layers are:
  rules (`test_rules.py`, `test_message_standard.py`), extraction and search (`test_library.py`),
  the code index (`test_code.py`, `test_web_frameworks.py`), the API (`test_server.py`), and the
  whole app in Chrome (`test_browser.py`).
- **Known gaps are recorded as strict expected failures**, so the list stays honest: closing one
  without removing its mark fails the suite.
- Development and commits are on `main`; the tests must pass before a change is committed, and a
  change in behaviour comes with a test that would have caught the old behaviour.

## Consequences

- Front-end unit tests began with ADR-011 (Vitest, `npm test`, also run by `npm run build`); the
  components are still covered by the browser flow only.
- Windows is the target but untested here; the scripts are syntax-checked only.
