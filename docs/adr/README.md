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
| [ADR-013](adr-013-patterns-view.md) | The Patterns view: idioms, how things are made, pairs, entry points and layers, hotspots, conventions, framework views (roadmap step 4, built) |
| [ADR-014](adr-014-traceability.md) | Traceability between Catalogue identifiers and code, as labelled mentions (roadmap step 13, built) |
| [ADR-015](adr-015-git-and-rename.md) | Git status, diff and commit (never push); rename symbol with a preview (roadmap step 14, built) |
| [ADR-016](adr-016-version-about-and-help.md) | A version, an About, and Help inside the app (roadmap step 5, built) |
| [ADR-017](adr-017-java-library-symbols.md) | Java library symbols read from class files: JDK and declared jars, no JVM (roadmap step 6, built) |
| [ADR-018](adr-018-change-impact.md) | The change-impact view: the closure over callers by layer, with routes and tests (roadmap step 7, built) |
| [ADR-019](adr-019-dead-code-and-signature-search.md) | Dead and unreachable code with certainty; signature-aware search (roadmap step 8, built) |
| [ADR-020](adr-020-index-snapshots.md) | Index snapshots, diffed: added, removed, changed, moved symbols and the callers affected (roadmap step 9, built) |
| [ADR-021](adr-021-convention-checks.md) | Convention checks from mined patterns, in a Checks segment and as editor markers (roadmap step 10, built) |
| [ADR-022](adr-022-tables-as-data.md) | Tables as data: a standard's table as an enum, compared with the enum the code has (roadmap step 11, built) |
| [ADR-023](adr-023-typescript-language-service.md) | A TypeScript language service: not built; added only if the measured by-name share on real code exceeds 25 %; `.d.ts` reading preferred first (roadmap step 12) |
| [ADR-024](adr-024-closing-the-resolution-gap.md) | Closing the resolution gap: type arguments through supertypes, typed callbacks, Spring Data queries as a rule, `.d.ts` files as library symbols (roadmap step 15, built) |
| [ADR-025](adr-025-rename-completeness.md) | Rename completeness, amending ADR-015: member accesses as references, imports, constructors and the file renamed with a class, collisions refused (roadmap step 16, built) |
| [ADR-026](adr-026-git-blame-and-history.md) | Git blame and history, read-only, amending ADR-015: blame in the editor, a file's and a symbol's history, one commit shown, dates on a standard's code mentions (roadmap step 17, built) |
| [ADR-027](adr-027-streamlit-removal.md) | Removing the switched-off Streamlit interface and its dependencies, completing ADR-007 (roadmap step 18, done) |
| [ADR-028](adr-028-portable-release.md) | Distribution as a portable release: embeddable Python, locked wheels, the app, the model and the scripts in one zip, built from a tag (roadmap step 19, built) |
| [ADR-029](adr-029-licensing.md) | Licensing: the project's own code MIT; PyMuPDF's AGPL governs a distributed copy, met by the public repository; releases given, not sold; what would reopen it (accepted) |
| [ADR-030](adr-030-field-layouts-as-code.md) | Field layouts as code, amending ADR-022: a table with a width column as a Java record or a TypeScript interface with offsets and widths, compared with the type the code has (roadmap step 20, built) |
| [ADR-031](adr-031-fixing-dead-links.md) | Fixing a PDF's dead links: a Links view that checks every internal link and bookmark at the raw object level, re-points the dead and mis-pointed ones by the document's own structure, and downloads the fixed file; refuses signed, locked and encrypted files (roadmap step 21, built) |
| [ADR-032](adr-032-bookmarks.md) | Bookmarks audited like links (wrong page, retitled, unchecked), the outline rebuilt from the headings on request, and a Bookmarks row in the Library's health report; amends ADR-031 (roadmap step 22, built) |
| [ADR-033](adr-033-searching-while-indexing.md) | Searching while a large document is indexed: a shorter model batch, the model wait outside the API lock, the model limited to half the threads, every indexing stage and a resumed job reported, keyword results ranked before highlighting; amends ADR-004 and ADR-007 (roadmap step 23, built) |

The order of work, and which record each step needs, is in [../roadmap.md](../roadmap.md).
