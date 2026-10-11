# Roadmap

The objective is ADR-001. Each step is built only once its record is agreed (ADR-009) and its
tests exist. The order is the one that keeps the index correct before anything is built on it.

| Step | What | Record | Tests first | Done when |
|---|---|---|---|---|
| 1 | **Type resolution and framework rules** (Java, TypeScript, JavaScript; Angular, React) | ADR-010 (accepted, built) | `tests/test_web_frameworks.py` gaps, plus chained calls, return types, templates, modules — all pass | **built**; the by-name share on the chosen real codebases is still to be measured (`python -m src.evaluate_code`) |
| 2 | **Incremental re-link on save; the writable editor**: save (atomic, checked against the file on disk), new/rename/move/delete files, project-wide find and replace | ADR-011 (accepted, built) | `tests/test_editing.py`, the API test, the browser flow, `web/src/code/drafts.test.ts` — all pass | **built**; a save settles in 0.04–0.06 s on the 3,000-file corpus, nothing else on disk is touched |
| 3 | **Examples panel and index completion**: context capture on the unsaved buffer, type filters, deterministic ranking, local recording of choices | ADR-012 (accepted, built) | `tests/test_examples.py`, `tests/examples_set.json` (judged), the API test, the browser flow, `web/src/code/assistant.test.ts` — all pass | **built**; precision@3 0.667 in both languages against 0.556/0.533 unranked and 0.185/0.267 text search (`python -m src.evaluate_examples tests/examples_set.json`) |
| 4 | **Patterns view**: idioms per type, call pairs, how things are made, entry points and layers, hotspots, conventions, framework views | ADR-013 (to write): which patterns, how mined, how shown | mined patterns on the fixtures match hand-counted ones | each pattern opens real examples |
| 5 | **Traceability** between Catalogue identifiers and code, both ways | ADR-014 (to write) | fixtures with a standard and code implementing it | an identifier's entry lists the code that handles it, and a rule's passage the code that implements it |
| 6 | **Git status, diff and commit; rename symbol with preview** | ADR-015 (to write): what git operations, never push by default; rename safety | git operations on a throwaway repository; rename on the fixtures | a rename changes only confirmed references |

Alongside every step: front-end unit tests (Vitest) for the components the step adds (ADR-008 names
their absence as a gap), and the ADR index updated.

## Decisions still open

- A TypeScript language service (needs Node.js on the target machine): decided after step 1's measures.
- Which real codebases (one Java, one Angular, one React) are used for measurement and the evaluation
  set, and who judges the examples.
- Removal of the switched-off Streamlit interface.
