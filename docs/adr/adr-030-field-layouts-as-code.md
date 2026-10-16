# ADR-030: Field layouts as code (amendment to ADR-022)

**Status:** accepted 2026-10-16; built the same day (roadmap step 20). Amends ADR-022's
"Tables as data"; ADR-022 itself stands: the enum rendering and the enum comparison are unchanged.

## Context

ADR-022 renders any table as an enum: one constant per row, the other columns as the constant's
values. That is the right shape for an enumeration table (a code list, a set of named values). It
is the wrong shape for the other table a standard is full of: the **field layout** — a message
word, a record, a header, a register — where each row is a field with a **width** (bits, bytes,
octets) and often a **position** (start bit, offset, or a `0–18` range), and the rows together
describe one value laid end to end. The fixture's `TABLE 5.1-1. M3.2I initial word` is one:
`Reference Number 281/001 19 bits`, `Strength 755/002 4 bits`. Rendered by ADR-022 it becomes an
enum of two constants, which nobody would write; what a developer writes by hand is a type with
two fields and, somewhere beside it, the offsets and widths used to pack and unpack it — and
that is what drifts from the standard when a width changes between editions.

The index already has what's needed: the joined table (continuations included, ADR-003/022), the
column classifier (name, code, number, text), the code index's types and their fields, and a
field's declaration line for reading a constant's value. The rendering is one more template; the
comparison is the enum comparison over fields instead of constants.

## Decision

### Recognising a layout

A joined table is a **layout** when it has a **width column**: a `number` column (ADR-022's
classifier) whose heading is a width word — `bits`, `bit(s)`, `width`, `length`, `size`, `bytes`,
`octets`, `len` — or, failing a heading, the only number column when another column is a
**position column**. A position column is one whose heading is `start`, `start bit`, `bit`, `bit
no`, `bits`, `offset`, `position`, `octet`, `byte` and whose values are numbers or ranges
(`0-18`, `0–18`, `0..18`, `bits 0-18`); a range gives both the start and the width (`end - start
+ 1`). A heading alone never decides: the values must fit. The unit is the heading's word (bits
unless it says bytes/octets); a table of bytes is a layout in bytes, not converted.

Positions: taken from the position column when there is one, as written; otherwise computed
cumulatively from the widths in row order from 0. Rows named `Total`, `Totals` or `Sum` are not
fields: their number is checked against the sum of widths. Rows named `Spare`, `Reserved`,
`Unused`, `Padding` or blank are fields (they occupy bits), named `SPARE_1`, `SPARE_2`… so a
layout stays contiguous. Nothing is inferred about bit order (MSB-first or not) or numbering base
(a standard counting bits from 1 stays as it counts); the rendering says what it took as given.

**Notes** are produced, not hidden, when the table doesn't add up: a gap or overlap between
consecutive positions, a total row that differs from the sum, a width that isn't a whole number.
A table that fails to be a layout is still a table: the enum rendering stays available, and the
layout rendering is simply not offered.

### The rendering

`GET /api/blocks/{id}/as-code?shape=layout&language=java|typescript&name=`. The response is
ADR-022's `AsCode` plus `shape`, `fields` (name, constant name, offset, width, the code column's
value if any), `unit`, `total` and `notes`. Deterministic, a template, no AI.

- **Java** — a `record`, one component per field, typed by width: `boolean` for 1 bit, `int` up
  to 31 bits, `long` up to 63, `byte[]` beyond (and for byte layouts wider than 8 bytes). The
  record body declares the layout as constants, one pair per field, and the total:

  ```java
  /** From TABLE 5.1-1. M3.2I initial word · 23 bits, offsets from 0 in row order */
  public record M32IInitialWord(int referenceNumber, int strength) {
      public static final int REFERENCE_NUMBER_OFFSET = 0, REFERENCE_NUMBER_BITS = 19;   // 281/001
      public static final int STRENGTH_OFFSET = 19, STRENGTH_BITS = 4;                   // 755/002
      public static final int TOTAL_BITS = 23;
  }
  ```

  The code column's value goes in the trailing comment, since it is a label and not a value of
  the type. No packing or unpacking methods are generated: how a project packs words is its own
  convention (its Patterns, ADR-013), and a wrong guess at it is worse than none.

- **TypeScript** — an `interface` with one property per field (`boolean` for 1 bit, `number` up
  to 53 bits, `bigint` beyond), and a `const … as const` layout object beside it:

  ```typescript
  /** From TABLE 5.1-1. M3.2I initial word · 23 bits, offsets from 0 in row order */
  export interface M32IInitialWord { referenceNumber: number; strength: number }
  export const M32IInitialWordLayout = {
    referenceNumber: { offset: 0, bits: 19 },   // 281/001
    strength: { offset: 19, bits: 4 },          // 755/002
    totalBits: 23,
  } as const;
  ```

The names: the type from the caption or the request (ADR-022's `type_name`), properties in
camelCase, constants in UPPER_SNAKE_CASE, duplicates suffixed as ADR-022 does. The comment line
says whether offsets came from the table or were computed, and the unit.

### Compare with a type

`GET /api/blocks/{id}/compare-layout?symbol=`: the layout's fields against a Java class or
record, or a TypeScript interface, class or type, chosen the way ADR-022's enum is chosen. Three
lists as before — **matched** (name normalised as ADR-022 normalises), **missing in the code**,
**extra in the code** (the type's fields that aren't in the table, constants excluded) — and a
fourth, **widths and offsets that differ**: for each matched field, when the type (or its file)
declares a constant named by the template's convention (`<FIELD>_BITS`, `<FIELD>_WIDTH`,
`<FIELD>_OFFSET`, `<FIELD>_START`), its value is read from the declaration line and compared with
the table's. A field whose width the code doesn't state is listed as *not stated*, not as a
mismatch. The TypeScript layout object's values are not symbols in the index, so for TypeScript
the fourth list is by name only unless constants of that convention exist; this is said in the
result rather than approximated.

Record components are the record's fields for this purpose and for the index generally: the
parser gains them as `field` symbols of the record (`w.referenceNumber()` is an accessor and
`Usages`, `Rename` and `Unused` should see components as they see fields; today they don't).
That is the one change outside `tables_as_code.py`; the fixtures hold no records, so no hand
count moves.

### In the Tables view

When the joined table is a layout, the card offers **As Java record** and **As TypeScript
interface** beside the enum buttons (which stay, since a code-list table with a width column
exists), with Copy and Insert as before, the fields and notes listed above the code; and
**Compare with type…**, which reuses the enum comparison's picker with the type kinds. A table
that is not a layout shows nothing new.

## Measures

On the fixture standard (tests first, `tests/test_tables_as_code.py`):

- `TABLE 5.1-1` is a layout in bits: `referenceNumber` at 0 for 19, `strength` at 19 for 4,
  total 23; the Java record and the TypeScript interface equal the expected text; the code column
  appears in the comments.
- `TABLE 5.1-2`, joined across the continuation: four fields, offsets 0/9/20/33, total 36.
- A table with a position column uses its values as written; a range column (`0-18`) gives both
  offset and width; a 1-bit field renders as `boolean`; a `Total` row is dropped and checked; a
  `Spare` row becomes `SPARE_1`; a gap produces a note and the rendering still succeeds.
- A table with no width column (the fixture's acronyms table) is not a layout: `shape=layout` is
  refused with the reason, and the card doesn't offer it.
- Compared with a fixture record declaring `REFERENCE_NUMBER_BITS = 19` and `STRENGTH_BITS = 5`
  and no `course`: matched/missing/extra equal the hand lists; `strength` is reported as 4 against
  5; `referenceNumber`'s offset is *not stated*.
- A record's components are `field` symbols with usages (parser test); the symbol counts of the
  existing fixtures are unchanged.
- The API test covers both routes; the browser test opens the Tables view on the fixture and sees
  the record.

## Consequences

- `src/research/tables_as_code.py` grows a layout detector, a second template per language and
  `compare_with_type`; `src/server/app.py` gains the `shape` query and `/compare-layout`; the
  `/blocks/{id}/table` response says `layout: true|false` with the unit so the card knows what to
  offer; `web/src/documents/DocInspector.tsx` gains the buttons and the fields list; `web/src/types.ts`
  the shapes.
- `src/code/parser.py`: record components as fields (Java only; TypeScript has no records).
- Help's Tables page gains a paragraph; ADR-022's status line points here.
- Not done, and said so: packing/unpacking code, bit-order and numbering-base inference, layouts
  spread over several tables (a message of several words stays several records), and any reading
  of prose clauses as code — tables remain the only thing rendered, for the reason ADR-022 gave.

## As built

- `src/research/tables_as_code.py`: `layout_of` (the detector: a range column by its values, else
  a number column headed by a position word for the offsets and one headed by a width word for the
  widths, else the only other number column beside a position column; Total rows checked, Spare
  rows kept as `SPARE_n`; gaps, overlaps and a differing total as notes), `render_layout` (the Java
  record and the TypeScript interface with its `…Layout` object; types by width in bits — a byte
  layout's widths count as eight bits each), `compare_with_type` (fields by normalised name;
  widths and offsets from constants named `<FIELD>_BITS|_WIDTH|_BYTES|_OCTETS|_LENGTH|_SIZE` and
  `<FIELD>_OFFSET|_START|_POSITION` among the type's members or the file's top-level constants,
  their values read from the declaration line since a constant's signature stops at `=`;
  `not_stated` per field and `by_name_only` when no constant exists). `as_code` takes `shape`.
- `src/code/parser.py`: a Java record's components are `field` symbols of the record, typed, with
  the component's type recorded as a type reference and bare reads inside the body as `use`
  references; the parameters are no longer locals of the type scope. `tests/test_code.py` covers
  it; the fixtures' symbol counts are unchanged (no fixture declares a record).
- **Noticed after 1.5.0 shipped (2026-10-16):** the build above left `PARSER_VERSION` at 2, so an
  index from 1.4.0 keeps its old symbols for files holding records until they change. Bumped to 3
  on `main` with a test that an older parser's files are read again on the next scan; it reaches
  users in the next release. Documents need no re-indexing: the extractor version is unchanged.
- `src/server/app.py`: `/blocks/{id}/table` answers `layout` and `unit`; `/blocks/{id}/as-code`
  takes `shape=layout`; `/blocks/{id}/compare-layout?symbol=`. A non-table or a non-layout is a 400
  with the reason.
- `web/src/documents/DocInspector.tsx`: when the joined table is a layout, a second row of buttons —
  **As Java record**, **As TypeScript interface**, **Compare with type…** — the fields, total and
  notes above the code, and the comparison's four lists (names only, said as such, when the code
  declares no constants). `web/src/types.ts` carries the shapes. Help's "Tables as code" gains the
  paragraph; ADR-022's status points here.

### Measures

- `tests/test_tables_as_code.py` (four new tests): the fixture's `TABLE 5.1-1` as the record and
  the interface, text for text, offsets 0/19, total 23, the `GRP/ITM` codes in the comments;
  `TABLE 5.1-2` joined across its continuation as four fields at 0/9/20/33, total 36; a position
  column used as written, a range column giving offset and width, a 1-bit field as `boolean`, a
  Total row dropped and checked, a Spare row kept, a gap and an overlap as notes; the acronym and
  message tables not layouts; types by width (`int`/`long`/`byte[]`, `number`/`bigint`); the
  comparison against a fixture record (`strength` 4 against 5, `referenceNumber offset` not
  stated, `course` extra) and against a TypeScript interface (names only).
- The ADR's measure named "the fixture's acronyms table" as the non-layout; in the fixture that is
  prose, not a table, so the non-layout cases are a two-column acronym table and the browser
  fixture's message table given to `layout_of` directly, and a prose block to the route (400).
- `tests/test_server.py`: the three routes on the fixture. `tests/test_browser.py` gains a second
  test: the message standard added, the Tables view on page 2 shows "A field layout in bits", the
  record and the interface render in the card.
- Suite: 202 passed (200 before this step's additions plus the parser test and the browser test;
  the counts of every earlier test unchanged).
