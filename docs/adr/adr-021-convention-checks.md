# ADR-021: Convention checks from mined patterns

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 10, written
before building it).

## Context

ADR-013 mines what's usual in a codebase: calls that go together, naming by package, idioms per
type. A method that breaks one of those is worth a look, and the evidence that it's unusual is the
set of methods that follow the pattern. That's linting whose rules come from the code itself, not
from a rule file, and it can be shown in the editor as the developer writes.

## Decision

- **Checks** (`src/code/checks.py`), each with the examples that establish the rule:
  1. **A missing companion:** a method calls `first` of a pair that goes together (ADR-013: support
     ≥ 3, confidence ≥ 0.8 in that direction) but not `second` — "`record` goes with `save` in 3 of
     3 methods; this one has no `save`".
  2. **A name against the package's convention:** a type in a package where ≥ 60 % (and at least
     three) of the types share a suffix, without it.
  3. **Error raised nobody raises:** `throw new X` where `X` is thrown nowhere else and another
     exception type is thrown ten or more times — likely a one-off.
  4. **A route handler not calling a service** (layering): when every other handler of the same
     controller type calls into the layer below, one that doesn't.
- Each finding carries: kind, the symbol, the line, a sentence, the examples (places that follow the
  rule), and a confidence (the pattern's). Findings are never about by-name links.
- **Where they show:** `GET /api/codebases/{id}/checks` for the whole codebase (a **Checks**
  segment in the Code panel), and in the editor as Monaco markers (information severity, never
  errors) on the saved file, refreshed after each save, with the examples in the hover text.
- Nothing is fixed automatically; a finding is a question, and the examples are how to answer it.

## Measures

- On the fixtures the findings equal a hand-made list (test); a method that follows every pattern
  has none.

## As built

`src/code/checks.py` (`checks_for`, whole codebase or one file), `GET /api/codebases/{id}/checks?file=`,
a **Checks** segment in the Code panel, and information markers in the editor on load and after each
save. Accessor names (`getX`, `isX`, `size`…) never make a companion pair, since a getter goes with
everything; the naming rule needs three types sharing the suffix; messages say "5 of 6 methods".
Tests: `tests/test_checks.py`, the API test.

## Consequences

- `src/code/checks.py`, one route, a Checks segment, markers in the editor, a `checks` call after
  save; builds on ADR-013's miner and ADR-012's statement shapes.
