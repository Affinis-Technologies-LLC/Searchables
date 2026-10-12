# ADR-025: Rename completeness (amendment to ADR-015)

**Status:** accepted 2026-10-11; built the same day (roadmap step 16). Amends ADR-015's "Rename
symbol"; ADR-015 itself stands. The five gap tests pass; measures below.

## Context

ADR-015's rename previews every place the index links and applies only what is ticked. Tried on
the fixtures before writing this, the preview is incomplete in four ways, each a place the text
would have to change for the program to still compile:

1. **Import lines.** `import com.shop.model.Order;` in four files, `import { fetchOrders, Order }
   from '../api/orders'` — imports are kept in `code_imports`, not as references, so no edit is
   offered. Renaming a class or an exported function leaves every importer broken.
2. **Constructors and the file.** `public Order(long id)` declares the constructor, a separate
   symbol named after the class; `new Order(7)` links to it, not to the class. Neither is offered
   when the class is renamed. A public Java class must also live in `Order.java`; the file isn't
   renamed, though `store.rename_file` (ADR-011) exists.
3. **Field accesses.** `this.selected.emit(user)` is not a reference: the index records calls,
   constructions, type uses and uses of imported names, but not a member access that isn't a call.
   Renaming a field therefore misses its reads and writes (`this.x = …`, `order.status`), in Java
   and TypeScript alike. The same hole makes **Usages**, **Impact** and **Unused** blind to fields:
   a field's usages list is nearly empty today.
4. **No collision check.** A new name that is already a member of the type (or of a supertype or
   subtype, with the same arity), or already a top-level name in the file or package, is accepted
   and produces a program that no longer compiles or silently changes meaning.

What already works and stays: Angular template bindings and interpolations are references and
are renamed; overrides are renamed together; a place whose text changed is skipped, not guessed.

## Decision

### Member accesses become references

- The parser records a reference of kind `use` for a member access that is not a call: Java
  `field_access` (`this.id`, `order.status`, `Outer.CONSTANT`) and a bare identifier inside a type's
  body that names one of the type's fields and no local or parameter (`id = value;`); TypeScript
  `member_expression` properties (`this.selected`, `user.name`) and the same bare identifiers in
  class bodies. Assignments count (the left side of `this.x = …` is a reference to `x`).
- They are linked like calls, through the receiver chain, to `field`/`variable` members (and to
  outside APIs: `System.out`, `document.body`); by-name ones stay by name with the usual label.
  The chain already exists for these nodes (it is what the linker follows for `this.x.y()`), so
  the parser's cost is the row, not new analysis.
- Nothing else changes meaning: Examples (ADR-012) and Patterns (ADR-013) count calls and
  constructions, not uses; Usages, Impact and Unused gain field edges — Unused's "field never
  read" becomes a real finding.

### Rename covers what the compiler would need

- **Imports.** Every `code_imports` row whose target is the symbol's file and whose names include
  the symbol's name (Java single import of the type; TypeScript `import { X }`, `import { X as Y }`
  (the `X` part only), `export { X } from`, `const { X } = require(…)`) is an edit of certainty
  `resolved`, selected by default. Wildcard imports need no edit. A Java nested type's import
  (`import a.b.Outer.Inner;`) edits the one segment.
- **Constructors with the class.** Renaming a Java class renames its constructors' declarations
  and every linked `new` reference to them; TypeScript constructors are named `constructor` and
  need nothing. The reverse is refused: a constructor is renamed through its class.
- **The Java file.** When the class is public, top-level, and its file is named after it, the
  preview offers "also rename `Order.java` → `OrderX.java`", ticked by default; applying it uses
  ADR-011's `rename_file` after the text edits, so the index, open tabs and the editor follow.
  TypeScript files are not renamed (their names aren't tied to the symbol; imports by path stay
  valid).
- **Collisions.** Before the preview, the new name is checked against: Java and TypeScript
  reserved words; the members of the symbol's type, its supertypes and subtypes with the same
  arity (for methods) or any arity (for fields); the top-level names of its file; the types of its
  Java package; the exports of its module. A collision is reported with the conflicting symbol's
  location and **Apply is refused**; the user picks another name. There is no "apply anyway".
- **By-name places** stay unticked, as in ADR-015. A by-name place that the new `use` references
  turn into a linked one is ticked, since it is now certain.

### What is not done

- No rename across codebases (a symbol of codebase A used by codebase B).
- No rename of a TypeScript module's file, of a package, or of a string that names a symbol
  (`"OrderService"` in a Spring bean name, a template `selector`). The preview lists string
  occurrences of the old name as **mentions**, unticked, for the user to judge — a text search,
  labelled as such, not a link.
- No update of comments or documentation beyond those mentions.

## Measures

- Tests first, strict expected failures, in `tests/test_git_and_rename.py`: each of the four gaps
  on the fixtures (Java class with imports, constructor and file; TypeScript function with a named
  import and an alias; a field with `this.x` reads and an assignment, in both languages; a
  collision refused with the location named), and the mentions list. After a rename, a rescan
  finds **no by-name reference to the old name** and the same number of linked usages under the new
  one — the compiler's check without a compiler.
- Field usages on the fixtures before and after: `Order#status` has 0 usages today; the test
  states the hand-counted number after.
- The reference table's growth from member accesses, measured on the 3,000-file corpus: recorded;
  the full scan may not take more than a tenth longer; a save's re-link stays under 0.1 s.
- The no-regression test of ADR-024 (`test_links_of_the_other_fixtures_only_improve`) keeps
  holding: new rows only, no target changes.

## Consequences

- `src/code/parser.py` records `use` references for member accesses (Java and TypeScript);
  `_PARSED_COLUMNS` is unchanged, but the next rescan re-reads every file (a version bump in
  `code_files`' reread rule, so existing indexes gain the rows).
- `src/code/rename.py` gains import edits (from `code_imports`), constructor and `new` edits, the
  file rename, the collision check and the mentions list; the preview response gains `file_rename`
  and `collision`; `RenameDialog.tsx` shows the file rename as a ticked line, a refused collision
  with its location, and mentions in their own group.
- Usages, Impact and Unused change for fields: more edges, and a field read nowhere becomes an
  Unused finding with the same certainty rules (ADR-019 names the exclusions; serialisation-only
  fields with an annotation stay excluded).
- Help's Code page gains the list of what a rename changes and what it refuses.

## As built

- **Member accesses as references** (`src/code/parser.py`): Java `field_access` nodes and bare
  identifiers that name a field of the enclosing type and no parameter or local (tracked per
  method and per type body, so `this.status = status` edits the field and leaves the parameter);
  TypeScript `member_expression` properties when the expression isn't the callee of a call. Linked
  through the chain (`this`, `T:Order`, `N:System`); a bare field name that belongs to an enclosing
  type is found by walking outwards (`_link`). `_NAME_KINDS["field"]` now includes `use`, so by-name
  reads show as such. Patterns ignore `use` rows (the view counts calls and constructions, as
  promised); Unused counts a type's members as used only when a link comes from **outside** the
  type, so a class whose fields only its own methods read is still unused.
- **Re-read on upgrade:** `code_files.parser` holds `PARSER_VERSION` (2); files read by an older
  parser are read again on the next scan.
- **Rename** (`src/code/rename.py`): import edits from `code_imports` (Java single and static
  imports; TypeScript named imports, the imported name only, so `import { fetchOrders as later }`
  keeps `later`); a Java class's constructors renamed with it and `new X()` through them;
  `file_rename` offered for a public top-level Java class whose file is named after it and done
  with ADR-011's `rename_file` after the text edits; `collision()` over the type's members, its
  supertypes' and subtypes' (methods by arity, fields by name), the file's top-level names and the
  Java package's types, and reserved words — a collision is reported in the preview and makes
  `apply_rename` raise; `mentions` from a string-literal search over the codebase (at most 200),
  listed and never edited. `POST …/rename` takes `rename_file`; the result carries `renamed_file`.
  The dialog shows the clash (Apply disabled), the file rename as a ticked line, and mentions as
  their own group.
- One scan-time change made on the way: files are committed in batches of fifty while reading,
  not one by one (an interrupted scan still keeps what was committed).

### Measures

- `tests/test_git_and_rename.py`: the five gap tests pass. After renaming `Order` → `Purchase`
  (14 files, imports, constructor, `new`, the file), a rescan finds **no by-name reference** to the
  old name in Java and the same number of linked usages under the new one; likewise `fetchOrders`
  → `loadOrders` with a named import and an alias. The API test covers the collision (`Order` →
  `Customer` refused, 400) and the file rename.
- Field usages: `Order#status` had 0 usages; it has 2 (`return status;`, `this.status = status`).
  `UserListComponent#selected`: declaration, `this.selected.emit`, and the `(selected)=` binding.
- Hand counts that moved, checked: none in Patterns (uses are excluded); Unused still reports
  `CustomerService` (its fields are read only by itself).
- The 3,000-file corpus: references 335,400 → 457,800 (+36 %, 122,400 member accesses). Scan time
  30.9 s → 37.4 s with the new rows (+21 %, over the ADR's tenth); committing in batches brings it
  to 31.7 s (+2.6 % net against ADR-024's figure). Stated plainly: the bound is met only with the
  batching. A save's re-link: 0.05 s.
- ADR-024's no-regression test still holds (rows added, no target changed).
