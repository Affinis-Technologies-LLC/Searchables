# Working in this repository

For people and coding agents alike. Read this, then the records it points to, before changing code.

## What this is

Searchables: a local research tool for standards PDFs and source code, with no AI in the loop
(a local embedding model is the one exception, ADR-002). A Python server (`src/server`) over a
SQLite library and code index; a prebuilt React front end (`web/`, built into `src/server/static`).
`APP_LAYOUT.md` says what each module does; `README.md` says what the app does.

## The rules

1. **Read `docs/adr/` first.** The records are the reasons behind the code. ADR-001 is the
   objective; ADR-002 to ADR-008 are decisions already built in; `docs/roadmap.md` is the order of work.
2. **No new behaviour without a record** (ADR-009). Write or update an ADR, get it agreed, then build.
3. **Tests before changes** (ADR-009). Protect what exists; write the gaps as strict expected
   failures; a changed behaviour ships with a test that would have caught the old one.
   Run `.venv/bin/python -m pytest` (needs `requirements-dev.txt`); the browser test needs Chrome.
   Front-end unit tests: `cd web && npm test` (also run by `npm run build`).
   A release is a bump of `VERSION`, a commit, a tag of the same number, and the archives built from
   that tag with `python deploy/build-release.py --target all` (ADR-016, ADR-028); a change to a view
   is reviewed against its help page in `docs/help/`.
4. **Keep to the recorded constraints**: everything local and offline (ADR-002); no LLM, nothing
   generated; rules that can be explained (ADR-003); additive schema changes (ADR-004); every code
   link states its certainty (ADR-006); the repository names no specific standard and uses none of
   its vocabulary (ADR-008); dependencies pinned by hash, `npm audit` clean (ADR-007).
5. **Work on `main`**; don't create branches. Don't commit or push unless asked.
6. **Made-up fixtures only.** Tests build their own PDFs and codebases (`tests/conftest.py`,
   `tests/codebase*`). Never add a real document or real restricted vocabulary.

## Where things are

| Area | Code | Tests |
|---|---|---|
| Extraction rules (clauses, tables, identifiers, provisions) | `src/extractor/` | `test_rules.py`, `test_message_standard.py` |
| Library, search, related, catalogue, health | `src/search/library.py`, `src/research/` | `test_library.py`, `test_message_standard.py` |
| Meaning model | `src/search/semantic.py` | stand-in in `conftest.py` (`model` fixture) |
| Background indexing | `src/search/indexer.py` | `test_library.py` |
| Code index: parser, linker, queries | `src/code/` | `test_code.py`, `test_web_frameworks.py` |
| API server | `src/server/app.py` | `test_server.py` |
| Front end | `web/src/` (`npm run build` after changes) | `test_browser.py` |
| Thresholds and settings | `src/config.py` | — |

## Measuring

- Document search quality: `python -m src.evaluate` against the user's own queries (kept out of the repo).
- Code linking quality: `python -m src.evaluate_code <folder>` reports the share of calls left by name, per language.
- Examples as you type: `python -m src.evaluate_examples tests/examples_set.json` (precision@3, MRR against two baselines).
