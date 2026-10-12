# ADR-024: Closing the resolution gap without a compiler

**Status:** accepted 2026-10-11; built the same day (roadmap step 15). The fifteen gap tests pass; measures below.

## Context

Every view of the Code side reads the same link table: Examples (ADR-012), Impact (ADR-018),
Unused (ADR-019), Changes (ADR-020), Checks (ADR-021), Rename (ADR-015) and the enum comparison
(ADR-022). A reference that is linked only by name weakens all of them at once, so the by-name
share is the one number that moves everything. Against an IDE with a compiler behind it, this is
the real gap; the other gaps (rename exactness, further refactorings) are this one in disguise.

What stays by name today, and why (from ADR-010's "What is not done" and the fixtures):

1. **Type arguments are not bound through supertypes.** `class OrderRepository extends
   JpaRepository<Order, Long>` leaves `repo.findById(id)` as `Optional<$T>` with `$T` unknown, so
   `.orElseThrow().getStatus()` is by name. The same for `implements Comparable<Order>`,
   `extends BaseService<Order>` within the codebase, and in TypeScript `extends Component<Props>`.
2. **Only a class's first type variable is tracked** (`$T`, ADR-017). `Map<String, Order>.get(k)`
   returns `V`, which is dropped; `Map.Entry<K, V>.getValue()` likewise.
3. **Callback parameters are untyped.** `orders.stream().filter(o -> o.isOpen())`,
   `orders.forEach(o -> …)`, `optional.ifPresent(o -> …)`, `users.map(u => u.id)`,
   `this.http.get<User>(url).subscribe(user => …)`, `fetch(url).then(r => r.json())`: `o`, `u`,
   `user` and `r` are unknown, so everything called on them is by name. ADR-010 named this gap
   explicitly; ADR-023 counts it as the main remaining TypeScript cause.
4. **Spring Data derived queries have no declaration.** `repo.findByStatus(s)` is declared nowhere
   (the framework derives it from the name at run time), so it is by name even with the jars read.
5. **Outside TypeScript APIs have no members.** `HttpClient.get` is an outside name
   (`@angular/common/http#HttpClient.get`) with no return type, so the chain stops there; the
   npm analogue of ADR-017 (reading `.d.ts` files) is ADR-023's preferred next step.

What is *not* a gap, checked before writing this: calls on a codebase interface already link to
the interface's member, and Impact, Unused and Examples already follow overrides from there
(`store.hierarchy`), so a "single implementation" rule adds nothing in Java; `var` and untyped
`const x = …` are already followed by chain.

A compiler stays out (ADR-001: nothing of the codebase is run; ADR-017: no JVM). Everything below
is rules over what the parser and the class-file reader already see.

## Decision

### Java and TypeScript: type arguments bound through supertypes

- The `extends` and `implements` references keep the **type arguments as written**
  (`code_refs.type_args`, e.g. `Order, Long`), parsed into a list.
- A library class and a codebase type both record **all their type parameters** in order
  (ADR-017's `$T` becomes `$T0`, `$T1`, …; a codebase type's parameters come from its declaration,
  which the parser already skips as `generics`).
- The linker, when it reaches a member through a supertype, **substitutes** the supertype's type
  variables with the arguments the subtype gave, transitively up the chain
  (`OrderRepository → JpaRepository<Order, Long>`: `findById` returns `Optional<Order>`;
  `BaseService<T>.load()` on `OrderService extends BaseService<Order>` returns `Order`).
- A type variable that cannot be bound (a raw type, a method-level variable) leaves the carried
  type empty, as today; nothing is guessed.

### Java and TypeScript: callback parameters typed from the receiver

- A fixed table of **functional members** says what their callback receives: the carried element
  (`forEach`, `filter`, `map`, `flatMap`, `anyMatch`, `allMatch`, `noneMatch`, `removeIf`,
  `sorted`, `min`, `max`, `ifPresent`, `ifPresentOrElse`, `Optional.map`, `Optional.filter`,
  `reduce`'s second parameter; in TypeScript `forEach`, `map`, `filter`, `find`, `findIndex`,
  `some`, `every`, `flatMap`, `reduce`'s second parameter, `sort`'s both), the carried value
  (`then`, `subscribe` with a function or an object's `next`, `pipe` operators `map`, `tap`,
  `filter`, `switchMap`, `mergeMap`), or nothing (anything else).
- The parser gives a lambda's or arrow function's parameters a type of the form **`C:<receiver chain>`**
  (the chain the lambda is an argument of, plus the member's name), and the linker resolves it to
  the receiver's carried type at link time with the table. Where a library member's generic
  signature already says the parameter is `Function<? super T, …>` (ADR-017 reads it), that takes
  precedence over the table.
- `map`'s **result** carries the type of the callback's body when the body is a single expression
  whose chain resolves (`orders.stream().map(o -> o.getCustomer())` carries `Customer`;
  `users.map(u => u.id)` carries whatever `id` is declared as); otherwise the carried type is
  empty, as today. Block bodies are not analysed.

### Java: Spring Data derived queries as a rule

- A call on a type that extends a Spring Data repository interface (`Repository`, `CrudRepository`,
  `JpaRepository`, `PagingAndSortingRepository`, by qualified name from the jars or by simple name
  when no jar is read) whose member is declared nowhere and whose name matches
  `(find|read|get|query|search|stream)(First|Top\d*)?By…`, `(count|exists|delete|remove)By…`
  links to the outside name `org.springframework.data.repository#<Interface>.<name>` with the
  return type the framework would give: the entity type (`findFirstBy…`, `…By…` returning one),
  `List<Entity>` (plural forms), `Optional<Entity>` when the codebase's other derived queries
  return it, `long`/`boolean` for `count`/`exists`. The entity is `$T0` bound by the rule above.
- The certainty of such a link is **`resolved` on the receiver and `rule` on the member** — a new
  value so that Impact and Rename can show it and the user can see which links come from a
  framework rule rather than a declaration. The rule is the first entry of a `src/code/frameworks.py`
  module that holds framework rules by name, so that the next ones (Angular `useClass` providers
  mapping a token to its implementation; React `forwardRef` already in ADR-010) have a home.

### TypeScript: declaration files read as library symbols (ADR-023's preferred step)

- For each dependency a `package.json` declares (ADR-010's manifests) that is present in
  `node_modules`, the package's **`.d.ts` files** are read with the TypeScript grammar already in
  use (tree-sitter, so no Node.js, nothing run): exported classes, interfaces, functions, constants
  and type aliases, with members, parameter counts, return types and the carried type, plus
  `export * from` and `export { } from` followed inside the package. The entry is the package's
  `types`/`typings` field or `index.d.ts`; `@types/<name>` packages are read for the package they
  describe. Deep imports (`@angular/common/http`) are resolved through the package's `exports`
  map or the folder's own `package.json`.
- Rows go into `code_library` with a `language` column (`java` for ADR-017's rows, `ts` for these)
  keyed by the package folder's path, size and mtime, shared by every codebase that resolves to
  that folder, re-read only when changed; `code_codebase_jars` gains the same rows for packages.
- The linker uses them as ADR-017 does for Java: an outside type's member gets its declaring
  interface and **return type**, so chains continue (`this.http.get<User>(url)` returns
  `Observable<User>` — explicit type arguments on a call bind the method's type variables;
  `.subscribe(user => …)` then types `user`). Completion on an outside type lists its members
  (`kind: "api"`) with the codebase's example counts. Targets stay strings; nothing in the index's
  meaning changes.
- Node.js's own API (`fs`, `path`, …) comes from `@types/node` when declared, the same way; the
  browser's from TypeScript's `lib.dom.d.ts` when the `typescript` package is installed in the
  codebase (it usually is), else `_GLOBALS` stays as it is.
- Off by `SEARCHABLES_LIBRARIES=0` like the jars; the Windows README's note on service-account
  access covers `node_modules` too.

### What is not done

- No inference through block-bodied lambdas, no overload resolution by argument types, no method
  type variables beyond those bound by explicit call arguments (`get<User>(…)`) or the functional
  table; no conditional or mapped TypeScript types (`Partial<T>`, `ReturnType<…>` read as their
  base and dropped); no Kotlin, no Lombok-generated accessors (a `@Getter` class's `getX()` stays
  by name — recorded as a candidate for `frameworks.py`); no Angular `useClass` yet (listed as the
  next rule, written when the measure asks for it).
- No TypeScript language service: ADR-023's threshold (25 % by name on the real Angular/React
  code) is re-measured **after** this ADR, and only then decides.

## Measures

- **Gap tests first**, one per cause above, as strict expected failures in a new
  `tests/test_resolution_gaps.py` on an extended fixture: supertype binding (codebase and jar),
  second type variable, Java callbacks (stream, Optional, forEach), TypeScript callbacks (array,
  promise, observable, `pipe`), `map`'s result, a derived query, `.d.ts` members and return types
  through a deep import, explicit type arguments on a call.
- **The by-name share** from `python -m src.evaluate_code` on both fixtures before and after
  (today: Java ≈ 2 %, TypeScript 11 % and 17 %), and on the real Java, Angular and React codebases
  once named; the baseline is recorded in this ADR's "As built" before the work starts.
- **No regression on existing links:** the fixtures' link table (reference → target, certainty)
  before and after is compared by a test; only additions and by-name → resolved changes are
  allowed. A link that changes from one resolved target to another fails the test and is judged
  by hand.
- **Time:** full scan of the 3,000-file corpus not more than a quarter slower; re-link of one file
  stays under 0.1 s (ADR-011); reading a package's `.d.ts` files is reported like the jars
  (`@angular/core` is the largest usual case).
- The judged examples set (ADR-012, `src.evaluate_examples`) re-run after: precision@3 and MRR may
  not fall.

## Consequences

- Additive schema (ADR-004): `code_refs.type_args`, `code_library.language`, type parameters as a
  list on library classes and codebase types (`code_symbols.type_params`); `_PARSED_COLUMNS` makes
  the next rescan re-read every file. The `rule` certainty value joins `resolved`, `supertype` and
  `by name` in the API and the inspector's labels; Impact's strength order becomes resolved <
  supertype < rule < by name.
- A new module `src/code/frameworks.py` (rules by framework, each with a comment naming what it
  stands in for); `src/code/declarations.py` (the `.d.ts` reader); `classfiles.py` tracks every
  type variable; the parser records `type_args` and `C:` parameter types; the linker's `_follow`
  substitutes bound type variables and types callback parameters.
- ADR-017's "only the first type variable" and ADR-010's "no inference across callbacks" are
  superseded here; ADR-023's follow-up is this ADR, and its threshold is applied to the number
  measured after it.
- Help's Code page gains a paragraph on what the certainty labels mean, including `rule`.
- Rename (ADR-015) and the Checks (ADR-021) get better for free; neither changes.

## As built

- **Parser** (`src/code/parser.py`): `extends`/`implements` references keep their type arguments
  (`ParsedRef.type_args`); types keep their type parameters (`ParsedSymbol.type_params`); a call's
  explicit type arguments are kept on the reference and in the chain step (`get<User>()`);
  untyped lambda and arrow-function parameters get the chain `C:<receiver chain>.<member>#<index>`,
  so references inside the body resolve through the receiver; a call whose one-expression lambda
  types its result (`map`, `flatMap`, `then`, `pipe(map/switchMap/…)`) records the body's chain
  (`ParsedRef.callback`, "v:" or "a:") and its chain step carries the position (`map(λ12:5)`).
  Two things found on the way and fixed: `await f<T>(x)` parses as a call of `await f`, which the
  reader now unwraps; and an interface's properties were not members, so chains through typed data
  (`item.supplier.rating()`) stopped — they are fields now. A member call's reference now sits at
  the member's own name, not the start of the expression.
- **Linker** (`src/code/store.py`): a type is (target, carried, bindings); bindings map a declaring
  type's variables to encoded types (`=12`, `=java.util.List<=7>`) that resolve from any file;
  `_member_bound` walks codebase supertypes with `_super_bindings`, then library supertypes
  (members inherited from a library type now resolve: `repo.findById()` on a type extending
  `JpaRepository`), then the framework rule; `_lib_result` binds class variables (`$T0`, `$T1`, …)
  and, for TypeScript rows, a method's own from explicit arguments; `_callback_parameter` and
  `_apply_callback` type callbacks from `_CALLBACK_PARAMS` / `CALLBACK_RESULTS`; `_CARRIERS` gains
  `Map`/`HashMap` (carrying the value type) and `_GLOBAL_RETURNS` gives `fetch` a `Promise<Response>`
  when no `lib.dom.d.ts` is read.
- **Class files** (`src/code/classfiles.py`): every class type variable is tracked by position;
  `code_jars.format` (2) makes the next scan re-read archives written by the earlier reader.
- **Declarations** (`src/code/declarations.py`): entries from `types`/`typings`/`main`, the `exports`
  map and secondary entry-point folders; `export *` and `export { A as B } from` followed (the
  re-exported name is the public one: `@acme/http#PageOf`); `export declare`, ambient and global
  declarations; names declared in the package or imported from another are written encoded in
  return types. Globals from `lib.es5/es2015…/dom.d.ts` when the `typescript` package is installed,
  named `#Array`, `#Promise`, `#fetch`. Rows share `code_library` (`language` column) and are read
  once per package folder (`code_jars.path`), re-read when its `package.json` changes.
- **Rules** (`src/code/frameworks.py`): Spring Data's CRUD members. **A correction to this ADR's
  text:** derived queries (`findByStatus`) are declared by the codebase's own repository interface
  and resolve as ordinary members; what the rule supplies is the CRUD API the framework's interfaces
  provide (`save`, `findById`, `findAll`, `count`, …) when their jar isn't on disk, typed in terms
  of the entity bound by `extends JpaRepository<Order, Long>`. Such links carry `code_refs.via =
  'rule'`, shown as certainty **rule** (inspector, usage rows). Angular `useClass` is not written.
- **Not done, beyond the ADR's list:** `collect(Collectors.toList())` (a method type variable bound
  by an argument) stays untyped; library supertypes pass bindings by variable name (class files
  don't keep supertype arguments); block-bodied lambdas; `Map.forEach((k, v) -> …)`.

### Measures

| | Java (`tests/codebase`) | Java (`codebase_examples`) | TypeScript (`codebase`) | TypeScript (`codebase_examples`) |
|---|---|---|---|---|
| Calls by name before | 4 of 16 (25.0 %) | 3 of 49 (6.1 %) | 1 of 9 (11.1 %) | 3 of 18 (16.7 %) |
| After, libraries unread | 3 of 16 (18.8 %) | 1 of 49 (2.0 %) | 0 of 9 (0 %) | 0 of 18 (0 %) |
| After, with the JDK read | 2 of 16 (12.5 %) | 0 of 49 (0 %) | 0 | 0 |

What is left on the fixtures: `unknownThing()` and a call on its result (deliberately unknown), and
`System.out.println` without a JDK. `tests/codebase_generics` (the gap fixture) links 30 of 30 Java
and 15 of 15 TypeScript calls. The real codebases are still to be measured (the baseline the
roadmap asks for), and ADR-023's threshold is applied to that number.

- No regression: the link tables of the other fixtures gained links and changed no target
  (`test_links_of_the_other_fixtures_only_improve`); three hand counts moved because a lambda is now
  linked (`Order#getId` has 3 callers; `User#getId` has none by name) and were checked by hand.
- Full scan of the 3,000-file corpus: 29.0 s → 30.9 s (+6.5 %); a save's re-link: 0.04 s, unchanged.
- The judged examples set (ADR-012): precision@3 0.667 and MRR 1.000 on both languages, unchanged.
