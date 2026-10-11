# ADR-010: Type resolution without a compiler, and framework conventions as rules

**Status:** accepted 2026-10-11; built the same day (roadmap step 1). The ten gap tests pass; the measurement
tool is `python -m src.evaluate_code <folder>`; the baseline on real codebases is still to be recorded.

## Context

ADR-006 links references through imports, declared types, inheritance and scope, and leaves the
rest by name. The assistant (ADR-001) ranks examples by type, so most expressions a developer
writes must resolve to a type, in Java, TypeScript and JavaScript alike, and Angular and React
conventions must be understood. Today, on the fixtures: Java leaves about 2% of calls by name; the
Angular and React fixtures leave calls through injected services, typed fields, wrapped default
exports and templates unlinked (`tests/test_web_frameworks.py`).

## Decision

### What the index records more of

- **Types of declarations.** Each symbol gets a `type` column: the declared or annotated type of a
  field, parameter or variable; the **return type** of a method or function (parsed from the
  signature; `Promise<T>`, `Observable<T>` keep `T` as the carried type); the class of a constructor.
- **Locals and parameters as symbols' scope**, not as symbols: the parser already tracks declared
  types within a method for Java; the same table of name → type is built for TypeScript (annotations,
  `const x = new X()`, `const x = f()` when `f` resolves and has a return type) and kept per method
  for the linker.
- **Constructor parameter properties** (`constructor(private users: UserService)`) become typed fields.
- **Decorators** become references of kind `annotation` on the class or member they decorate, whatever
  node the grammar hangs them on.
- **Wrapped default exports**: `export default f(X)` for `f` in a known set (`React.memo`, `memo`,
  `forwardRef`, `connect(...)`, `styled(...)`, `observer`) and generally for any single-argument call
  whose argument is a top-level symbol, make `X` the default export.
- **Angular templates read as code.** `.html` files named by `templateUrl`, and inline `template`
  strings, are parsed with a small template reader (not tree-sitter: Angular's syntax is its own):
  element tags that are component selectors → references of kind `jsx` to the component; property
  and event bindings (`[title]`, `(selected)`) → references to the child's `@Input`/`@Output` fields;
  expressions in `{{ }}`, `( )` and `[ ]` → references to the host component's members. `*ngFor`
  locals are scoped. Templates are files in the index, with lines, so usages open them.
- **Module metadata**: `@NgModule` `declarations`, `imports`, `providers`, `bootstrap` arrays → references
  to the listed classes.

### How linking changes

- **Receiver typing by chain.** A call's receiver is resolved left to right: a name is a local, a
  parameter, a field (through `this.`), an import binding or a type; a call in the chain contributes
  its target's return type; `.subscribe`, `.pipe`, `.then` and array methods carry the type of what
  they're called on (the carried `T` for observables and promises). The first link that fails leaves
  the rest by name.
- **Members through types.** With a receiver type that's a symbol of the codebase, the member is
  looked up on it and its supertypes (as now). With an outside type (`HttpClient` from
  `@angular/common/http`), the reference's target is the outside API name `package#Type.member`, so
  it counts as a use of that API.
- **Hooks and components.** A call to an imported or local `useX` function is a hook use; a JSX
  element resolves through its binding as now, including wrapped exports.
- **Incremental re-linking** (needed for the editor, ADR-011): re-link the references of a changed
  file and the references elsewhere whose target was in that file, using the same code as the full
  pass. The full pass stays for rescans.

### What is not done

- No generics beyond the carried `T`; no overload resolution by argument types beyond count; no
  inference across callbacks' parameters (`users => users.map(u => u.id)` leaves `u` untyped);
  no TypeScript language service (deferred by ADR-001 until these rules are measured).

## Measures

- The five expected failures in `tests/test_web_frameworks.py` pass, plus new ones added first for:
  chained calls, return types, template bindings, module metadata, carried types.
- The **by-name share** (unlinked calls over all calls), reported per language by a new
  `python -m src.evaluate_code <codebase>`, on one real Java, one Angular and one React codebase
  chosen by the user; the baseline is recorded before the work and the target is below 10% for Java
  and TypeScript, with the JavaScript figure recorded as the input to the language-server decision.
- The scan time per file on the 3,000-file corpus doesn't grow by more than a quarter.

## Consequences

- The `code_symbols` table gains a `type` column and `code_refs` a `chain` column; templates add a
  file kind (`html`), a `code_components` table and a reader (`src/code/templates.py`); the linker
  gains a chain resolver with carrier types. All additive (ADR-004).
- Outside APIs are named by npm package (`@angular/common#HttpClient.get`), not by entry point.
- Re-linking one file takes about 0.9 s on the 3,000-file corpus (it still loads every symbol);
  ADR-011 must bring that down for saving in the editor.
- Certainty labels stay as they are; nothing resolved by these rules is shown as more certain than
  "linked", and template references are labelled as coming from a template.
