# ADR-022: Tables as data

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 11, written
before building it). Amended by ADR-030 (2026-10-16): a table with a width column is also rendered as
a field layout — a record or an interface with offsets and widths — and compared with a type.

## Context

Standards are full of enumerations and field tables: a name, a code, a width or range, a unit.
Developers transcribe them into enums and constants by hand, and the enum drifts from the table as
editions change. The index already has every table as data (columns and rows, joined across
pages, ADR-003); the code index has every enum and its constants. Both sides are structured, so a
table can be rendered as code and compared with the enum that exists.

## Decision

- **A table as code** (`GET /api/blocks/{id}/as-code?language=java|typescript&name=`): the joined
  table's columns are classified by their values: the **name** column (the first column of mostly
  words), **code** columns (identifiers, numbers with separators, hex), **number** columns (widths,
  lengths, ranges, counts), the rest as text. Rendered deterministically as a Java `enum` with one
  constant per row, its constructor arguments being the other columns (strings or numbers), or as
  a TypeScript `export const` object `as const`. Constant names are the name column in
  UPPER_SNAKE_CASE; the enum's name comes from the caption or the request. No AI; it's a template.
- **Compare with an enum** (`GET /api/blocks/{id}/compare-enum?symbol=`): the table's constants
  against the enum symbol's members: matched, missing in the code, extra in the code, and for
  matched constants whose declaration carries values (`REFERENCE_NUMBER("281/001", 19)`), the
  values of the table's code and number columns that the declaration doesn't contain.
- **In the document inspector's Tables view:** **As code** (language choice, Copy, Insert into the
  editor at the cursor) and **Compare with enum…** (pick a codebase and an enum by name), with the
  result as three lists that open the code or the table.

## Measures

- On the fixture standard, TABLE 5.1-1 renders as the expected Java enum and TypeScript object;
  compared with a fixture enum, matched/missing/extra equal the hand-made lists (tests).

## As built

`src/research/tables_as_code.py` (`classify_columns`, `render`, `as_code`, `compare_with_enum`), routes
`GET /api/blocks/{id}/as-code?language=&name=` and `GET /api/blocks/{id}/compare-enum?symbol=`, and in the
document inspector's Tables view: **As Java enum**, **As TypeScript** (Copy, Insert into the open file) and
**Compare with enum…** (codebase, enum by name). Only upper-case members count as the enum's constants.
Tests: `tests/test_tables_as_code.py` on the fixture standard, the API test.

## Consequences

- `src/research/tables_as_code.py`, two routes, controls in the Tables view; `insertAtCursor` from
  ADR-012 is reused for Insert.
