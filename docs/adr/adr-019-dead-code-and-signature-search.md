# ADR-019: Dead and unreachable code; signature-aware search

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 8, written
before building it).

## Context

The index knows every declaration and every linked reference, so what is *never* referenced is a
query: methods nothing calls, routes nothing reaches, exports nothing imports. It also stores every
symbol's declared or return type (ADR-010), so "methods taking a `User` and returning `Optional`" is
a query too, not a grep. Both must respect the certainty labels: a method with a by-name reference
isn't dead, it's uncertain, and the view must say which.

## Decision

### Unused code (`GET /api/codebases/{id}/unused`)

- **Methods and functions never called:** no linked call, no call through a supertype method they
  override, and (for JS/TS) not exported or exported but imported nowhere. Entry points are never
  listed: `main`, route handlers (served endpoints), overrides of library methods (`toString`,
  `equals`, lifecycle methods such as `ngOnInit`, `componentDidMount`), test methods, constructors,
  `@Bean`/`@Override`-annotated and other annotated methods (a framework may call them), and public
  Java methods of exported types when the codebase is a library (a setting).
- **Routes nothing calls:** served endpoints with no matching client call (already in the APIs
  view; listed here too).
- **Exports nothing imports:** JS/TS exported symbols no file imports (by name or default), other
  than entry files (`index.*`, `main.*`, files named in `package.json`'s `main`/`exports`/`bin`).
- **Types nothing refers to:** classes and interfaces with no linked reference of any kind.
- **Each item carries a certainty:** *no reference at all*, or *only by-name references* (count
  shown). The default list is the former; the latter is a switch, never mixed in.

### Signature-aware search (`GET /api/codebases/{id}/signatures`)

A query form over the stored symbols: kind, name (prefix/contains), **declared or return type**
(simple name, matching the stored text's base type and ignoring generics unless given), **parameter
count**, **parameter types** (from the signature text), and **owner type**. "Methods taking a `User`
returning `Optional`" is `kind=method&param=User&returns=Optional`. Results open in the editor with
the usual inspector. Available in the Code panel's Search as a third mode, **Signature**.

## Measures

- On the fixtures the unused list equals a hand-made one, and nothing in it has a linked reference
  (test); the by-name switch lists exactly the methods whose only references are by name.
- Signature queries on the fixtures return exactly the expected symbols (test).

## As built

`src/code/unused.py` (`unused_in`), `src/code/signatures.py` (`search_signatures`, `parameter_types`),
routes `GET /api/codebases/{id}/unused` and `…/signatures`, an **Unused** segment in the Code panel
with the by-name switch, and a **Signature** mode in the Code search. Marker annotations (`@Override`,
`@Deprecated`…) don't make a method an entry point; others (`@Bean`, `@Test`…) do. Tests:
`tests/test_unused_and_signatures.py` (hand-made lists on the fixtures), the API test.

## Consequences

- `src/code/unused.py`, `src/code/signatures.py`, two routes, an **Unused** segment in the Code
  panel and a **Signature** search mode; `CODE_LIBRARY_PUBLIC` setting (public methods of exported
  types count as used) off by default.
