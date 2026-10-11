# Architecture decision records

One file per decision, numbered in the order they were written. A record is never edited to say
something different; a later record supersedes it and says so. ADR-001 is the objective; ADR-002 to
ADR-008 record the decisions already built into the code, ADR-009 the way of working,, so that work towards the objective keeps
to them or supersedes them knowingly.

| Record | Decision |
|---|---|
| [ADR-001](adr-001-iniitial-objective.md) | The objective: a code assistant without AI, and a web editor, inside Searchables |
| [ADR-002](adr-002-local-only-no-llm.md) | Everything runs on the user's machine; no LLM; embedding models only of known provenance |
| [ADR-003](adr-003-rule-based-extraction.md) | Document understanding is rule-based, explainable, and discovered per document |
| [ADR-004](adr-004-storage-and-indexing.md) | One SQLite library; background, resumable indexing; versioned extraction |
| [ADR-005](adr-005-search.md) | Keyword and meaning search fused by rank; thresholds measured, not guessed |
| [ADR-006](adr-006-code-index.md) | Source code parsed with tree-sitter and linked without a compiler, with every link's certainty stated |
| [ADR-007](adr-007-server-and-front-end.md) | A local API server and a prebuilt browser front end |
| [ADR-008](adr-008-security-and-testing.md) | How restricted material is handled, and how the code is protected by tests |
| [ADR-009](adr-009-adr-first-and-tests-first.md) | A record before anything new; tests before any change; how people and agents work the same way |
| [ADR-010](adr-010-type-resolution-and-framework-rules.md) | Type resolution without a compiler, and Angular/React conventions as rules (roadmap step 1, built) |
| [ADR-011](adr-011-writable-editor.md) | The writable editor, what the server may write, and the index on save (roadmap step 2, built) |
| [ADR-012](adr-012-examples-and-completion.md) | Examples as you type and completion from the index — context, filters, ranking, evaluation set (roadmap step 3, built) |

The order of work, and which record each step needs, is in [../roadmap.md](../roadmap.md).
