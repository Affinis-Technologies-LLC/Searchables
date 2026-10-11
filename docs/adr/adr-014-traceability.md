# ADR-014: Traceability between Catalogue identifiers and code, as mentions

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 13, written
before building it). Scope narrowed from ADR-001's "the code that handles it" to what can be
shown to be true.

## Context

ADR-001 planned a trace from a Catalogue identifier to the code that implements it, and back. The
doubt recorded in the roadmap stands: a standard is implemented across the whole architecture, so
"the code that handles M3.2" is a judgement the index can't make; a list that claims it would be
wrong often enough to be ignored. What the index *can* say exactly is where an identifier's text
appears in the code: as a string literal, in a comment, or as a name shaped from it
(`GRP_281_ITM_001`, `M3_2`). That is evidence a developer can use, labelled for what it is.

## Decision

- **Mentions, not implementation.** A trace is a *mention* of an identifier in a file, with a
  certainty: **exact** (the identifier as written, or its core such as `281/001` of
  `GRP/ITM 281/001`, found in the text), or **by name** (a symbol whose name, with separators
  removed and case ignored, equals the identifier's: `M3_2` for `M3.2`, `GRP281ITM001` for
  `GRP/ITM 281/001`). Nothing else is claimed.
- **Both ways:** `GET /api/catalogue/code?id=…` lists the mentions of an identifier across the
  codebases (file, line, the line's text, certainty); `GET /api/code/files/{id}/identifiers` lists
  the Catalogue identifiers mentioned in a file, with lines, from the documents in the library.
- **Where it shows:** a Catalogue entry gains an **In the code** section; the code inspector's
  **File** view gains **Identifiers from the documents**, each opening the Catalogue entry.
- Short identifiers (fewer than three characters, or plain numbers) are never traced: they'd match
  everything.

## Measures

- On the fixture standard and a fixture file mentioning `281/001` in a string and `M3_2` as a
  constant, the two lists equal the hand-made ones, with the right certainty (test).

## As built

`src/research/trace.py` (`name_forms`, `code_mentions`, `identifiers_in_file`), routes
`GET /api/catalogue/code?id=` and `GET /api/code/files/{id}/identifiers`; a Catalogue entry's **In the
code** section and the code inspector's File view's **Identifiers from the documents** (each opening the
entry). The file side uses the Catalogue's switched-on families only, as the Catalogue does. Tests:
`tests/test_trace.py`, the API test.

## Consequences

- `src/research/trace.py`, two routes, two small view additions. ADR-001's traceability item is
  met in this narrower, honest form; a conformance map (ADR-001's larger idea) stays out.
