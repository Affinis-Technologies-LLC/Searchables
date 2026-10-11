# ADR-013: The Patterns view

**Status:** accepted 2026-10-11 (the whole roadmap was agreed as a list; this is the record for
step 4, written before building it).

## Context

ADR-001's third layer: discovery of an unfamiliar codebase. The index knows every call, construction,
type use, import, endpoint, component and template; what it doesn't show is what is *usual*: what
gets called on a repository and in what order, which calls always go together, how a type is
obtained, where the code is entered and in what layers it's organised, what's used most, and what
the naming conventions are. Developers work these out by reading; the index can count them.

## Decision

A **Patterns** view in the Code panel, computed from the index for one codebase and cached until the
next scan or save. Every pattern opens real examples (the usages it was counted from), and every
number says what it was counted over. Mined with counts and thresholds, no model.

| Pattern | How it's mined | Shown as |
|---|---|---|
| **Idioms per type** | For each type with at least `PATTERN_MIN` (3) call sites, the ordered pairs of members called on it within one method, counted over methods | "`find` then `save`: 4 methods"; each opens the methods |
| **How things are made** | For each type: `new` constructions; fields and constructor parameters of that type (injection); calls whose return type is that type (factory) | "Obtained by injection in 6 places, constructed in 1" |
| **Pairs that go together** | Pairs of call names in the same method (by member name, so overloads and sibling types count as one), support ≥ 3 methods, confidence ≥ 0.8 in at least one direction, reported in that direction; `begin`/`commit`, `lock`/`unlock`, `open`/`close` | "`record` goes with `save` (3 of 3 methods)" |
| **Entry points and layers** | Served endpoints → their handlers → callees to depth 3; packages ordered by the direction of the dependency map (a package depended on by more than it depends on is lower) | Endpoint → handler → service → repository, per endpoint |
| **Hotspots** | Most-referenced symbols and files (linked references only) | Top 20 of each |
| **Conventions** | Name suffixes and prefixes by kind that cover ≥ 60 % of a package's types; where tests live (folders whose files are mostly test-named); how errors are raised (`throw new X` by type) | "Types in `service` end in `Service` (3 of 3)" |
| **Framework views** | Angular: components with selector, template file, inputs and outputs, injected services; React: which component renders which (from JSX), hooks each uses | Trees and tables |

Counts are over linked references; by-name links are excluded so a pattern never rests on a guess.
The data is `GET /api/codebases/{id}/patterns`, computed in `src/code/patterns.py`.

## As built

`src/code/patterns.py`, `GET /api/codebases/{id}/patterns`, a **Patterns** segment in the Code panel
with a section chooser; every row opens the places it was counted from. Test files (named `*Test.java`,
`*.test.ts`, `*.spec.ts`, under `__tests__`) are left out of the naming conventions. "How errors are
raised" counts `throw new X` through the statement shapes ADR-012 added. Tests: `tests/test_patterns.py`,
hand counts on `tests/codebase_examples` and `tests/codebase_web`.

## Options considered

- **Sequential pattern mining over whole method bodies** (longer sequences). More to show, harder to
  read; ordered pairs cover the idioms people ask about. Longer sequences can follow if pairs prove
  useful.
- **Patterns as a report file.** The view is the report; it opens examples, a file can't.

## Measures

- On the fixtures, every mined count equals a hand count (tests).
- The view on the 3,000-file corpus computes in under 2 s and is cached. **Measured: 4.5 s** (260,000
  linked references, every method of that corpus making 13 calls), then 20 ms from the cache; the
  target wasn't met and the cache makes it a once-per-change cost. Left as is.
- Each pattern row opens at least one example.

## Consequences

- `src/code/patterns.py`, a cache keyed by codebase and its last change, a `Patterns` segment in
  the Code panel; step 10 (convention checks in the editor) builds on these counts.
