# Roadmap

The objective is ADR-001. Each step is built only once its record is agreed (ADR-009) and its
tests exist. The order is the one that keeps the index correct before anything is built on it.

| Step | What | Record | Tests first | Done when |
|---|---|---|---|---|
| 1 | **Type resolution and framework rules** (Java, TypeScript, JavaScript; Angular, React) | ADR-010 (accepted, built) | `tests/test_web_frameworks.py` gaps, plus chained calls, return types, templates, modules — all pass | **built**; the by-name share on the chosen real codebases is still to be measured (`python -m src.evaluate_code`) |
| 2 | **Incremental re-link on save; the writable editor**: save (atomic, checked against the file on disk), new/rename/move/delete files, project-wide find and replace | ADR-011 (accepted, built) | `tests/test_editing.py`, the API test, the browser flow, `web/src/code/drafts.test.ts` — all pass | **built**; a save settles in 0.04–0.06 s on the 3,000-file corpus, nothing else on disk is touched |
| 3 | **Examples panel and index completion**: context capture on the unsaved buffer, type filters, deterministic ranking, local recording of choices | ADR-012 (accepted, built) | `tests/test_examples.py`, `tests/examples_set.json` (judged), the API test, the browser flow, `web/src/code/assistant.test.ts` — all pass | **built**; precision@3 0.667 in both languages against 0.556/0.533 unranked and 0.185/0.267 text search (`python -m src.evaluate_examples tests/examples_set.json`) |
| 4 | **Patterns view**: idioms per type, call pairs, how things are made, entry points and layers, hotspots, conventions, framework views | ADR-013 (accepted, built) | `tests/test_patterns.py`: hand counts on the fixtures — all pass | **built**; every row opens its examples; 4.5 s on the 3,000-file corpus, then cached |
| 5 | **Version, About and Help in the app** | ADR-016 (accepted, built) | `tests/test_help_and_version.py`, the API test, the browser flow, `markdown.test.ts` — all pass | **built**; `VERSION` 1.4.0 |
| 6 | **Java library symbols from class files**: members of outside APIs (`List`, `Optional`, Spring) read from the jars a build declares, without a compiler or JVM | ADR-017 (accepted, built) | `tests/test_library_symbols.py` — all pass (JDK ones skip without a JDK) | **built**; Java by-name on the fixture 4 → 3 of 16; completion lists library members; the real-codebase measure is still owed |
| 7 | **Change-impact view**: everything transitively reachable through callers of a symbol, grouped by layer (endpoint → service → repository), with certainty | ADR-018 (accepted, built) | `tests/test_impact.py`: hand counts — all pass | **built**; the inspector's Impact view |
| 8 | **Dead and unreachable code; signature-aware search**: declared but never called, routes nothing calls, exports nothing imports; queries over stored types ("methods taking a `User` returning `Optional`") | ADR-019 (to write) | fixtures with known dead code; query tests | lists with certainty labels, no false alarms from by-name links |
| 9 | **Index snapshots, diffed**: two checkouts or before/after a change, as new/removed/changed/moved symbols with the callers affected | ADR-020 (accepted, built) | `tests/test_snapshots.py` — all pass | **built**; the Changes segment |
| 10 | **Convention checks from mined patterns**: a method that breaks an idiom the codebase itself establishes is flagged in the editor with the examples that establish it | ADR-021 (accepted, built) | `tests/test_checks.py` — all pass | **built**; Checks segment and editor markers |
| 11 | **Tables as data**: a standard's enumeration or field table as a code-shaped view, offered as an Insert and diffed against the enum the code already has | ADR-022 (accepted, built) | `tests/test_tables_as_code.py` — all pass | **built**; As code and Compare with enum in the Tables view |
| 12 | **A TypeScript language service**, if the by-name share measured on the real Angular/React code is too high after step 1 | ADR-023 (accepted: a decision procedure) | by-name share before and after | **open on the measure**: built only above 25 % by name on the real codebases; reading `.d.ts` files of declared packages is the preferred first step |
| 13 | **Traceability** between Catalogue identifiers and code, both ways | ADR-014 (accepted, built as mentions) | `tests/test_trace.py` — all pass | **built** in the narrow form: where an identifier's text appears in the code (exact) or a symbol is named after it (by name), and which identifiers a file mentions; no claim of implementation, per the doubt recorded on 2026-10-11 |
| 14 | **Git status, diff and commit; rename symbol with preview** | ADR-015 (accepted, built) | `tests/test_git_and_rename.py` — all pass | **built**; Git segment; Rename… on a symbol |

Alongside every step: front-end unit tests (Vitest) for the components the step adds (ADR-008 names
their absence as a gap), and the ADR index updated.

## Decisions still open

- A TypeScript language service: ADR-023 makes it a decision by measure (above 25 % by name on the real
  Angular/React code, after reading `.d.ts` files has been tried).
- Which real codebases (one Java, one Angular, one React) are used for measurement and the evaluation
  set, and who judges the examples.
- Removal of the switched-off Streamlit interface.
