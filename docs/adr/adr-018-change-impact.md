# ADR-018: The change-impact view

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 7, written
before building it).

## Context

"If I change this, what could break?" is answered today by following callers one level at a time
in the inspector's Calls tree. The question is about the transitive closure: every method that
reaches the symbol through calls, the HTTP routes whose handlers are among them, the tests that
exercise it, grouped so the answer reads as layers (endpoint → service → repository) rather than as
a list.

## Decision

- **Impact of a symbol** (`GET /api/code/symbols/{id}/impact`): the closure over callers. For a
  method or function: the methods that call it, those that call them, and so on. For a type: the
  references to the type and to each of its members, then their callers. Edges come from
  `usages()`, so each carries its certainty: linked, through a supertype (a call made through an
  interface method the symbol overrides), or by name only.
- **Bounds:** depth 8 and 400 symbols; the answer says when it was cut. By-name edges are
  followed only when asked (`by_name=1`), and the nodes they add are marked.
- **Grouped by layer:** Java by package in the order ADR-013's layers gives (most depending first);
  JavaScript and TypeScript by top folder. Each node shows its depth (the shortest call distance
  from the symbol) and the certainty of the weakest edge on that path.
- **Endpoints and tests reached:** served routes whose handler is in the closure; test files
  (ADR-013's test naming) with the symbols in them.
- **In the inspector**, an **Impact** view for the symbol: the layers with their nodes, the routes
  and tests, a switch for by-name links, and each node opening its usages of the next node down.

## Measures

- Closure on the fixtures matches a hand count (test): `OrderRepository#save` reaches `place`,
  `create` (and so the route `POST /api/orders`) and the test `savesAnOrder`.
- On the 3,000-file corpus a symbol with thousands of transitive callers answers in under a second
  and says it was cut.

## As built

`src/code/impact.py` (`impact_of`), `GET /api/code/symbols/{id}/impact?by_name=1`, an **Impact** view
in the code inspector with the by-name switch, routes and tests first, then the layers with each node
indented by its call distance. Tests: `tests/test_impact.py`, the API test. On the 3,000-file corpus a
symbol everything reaches is cut at 400 nodes in well under a second.

## Consequences

- `src/code/impact.py`, one route, an inspector view; builds on ADR-013's layers.
