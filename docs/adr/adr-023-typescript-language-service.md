# ADR-023: A TypeScript language service — decided by the measure

**Status:** accepted 2026-10-11 as a decision procedure; the service itself is **not built**.
Roadmap step 12.

## Context

ADR-001 deferred a TypeScript language service (`tsserver`, which needs Node.js on the target
machine) until the by-name share on real Angular and React code had been measured after ADR-010's
rules. The rules, ADR-012's platform globals and ADR-017's approach to libraries are now in place.
What the fixtures show: TypeScript calls by name 1 of 9 on `tests/codebase` (11 %), 3 of 18 on
`tests/codebase_examples` (17 %), the rest being callbacks' untyped parameters and chained calls
on results of outside APIs. Real codebases are the measure that counts, and none has been named.

## Decision

- **Not built now.** The service is added only if `python -m src.evaluate_code <codebase>` on the
  real Angular and React codebases reports a TypeScript by-name share above **25 %** after a
  reasonable attempt at closing the gaps with rules (an ADR-010-style list of gap tests first).
- **If built, how:** the server would run `tsserver` as a child process only on request and only
  for resolution and completion of TypeScript files (never for building), from a Node.js the
  machine already has (`SEARCHABLES_NODE`, `node` on `PATH`); the index stays the source of truth
  for everything else; results from the service get the certainty label `resolved` and are
  recorded in the index like any link; when Node.js is absent the app works as now. This would be
  the one place the app runs a program, and ADR-001's "nothing is run" would have to be amended
  to "nothing of the codebase is run" with the user's explicit opt-in (a setting, off by default).
- **The npm-side analogue of ADR-017** (reading `.d.ts` files of declared packages from
  `node_modules` to know outside APIs' members and return types) is the next thing to try before a
  language service, since it keeps everything in the index and runs nothing. It is recorded here
  as the preferred follow-up (ADR to write when the measure is in).

## Consequences

- Nothing changes in the code. `docs/roadmap.md` keeps step 12 open on the measure; the real
  codebases are still to be named.
