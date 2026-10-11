# ADR-006: Source code parsed with tree-sitter and linked without a compiler

**Status:** accepted

## Context

The tool browses codebases (Java, JavaScript, TypeScript, JSX/TSX) the way an IDE lets a reader
trace code, on machines with no compiler, JDK or Node.js runtime for the app itself.

## Decision

- Files are parsed with **tree-sitter** grammars (MIT; prebuilt for Windows, macOS, Linux). A parser,
  not a model: it copes with files that have errors and records what it could read.
- The index keeps symbols (with signatures and parameter counts), references (with the receiver and
  argument count as written), imports, declared libraries from build files, and HTTP endpoints, plus
  each file's text for searching and display. Build output, dependencies and bundles are skipped.
- **Linking is done in one pass over the whole index**, after parsing: through imports (including
  `tsconfig` path aliases and `require`), declared types, inheritance and scope, resolving Java types
  the way `javac` does (enclosing types, imports, package, `java.lang`, one wildcard import).
- **Every link states its certainty**: linked, through a supertype (an interface method the symbol
  implements), or by name only. The interface never shows a by-name link as certain.
- A folder is indexed where it is; the app writes nothing into it. Rescans re-read changed files only.
- Precision is to be improved within this design (ADR-001, layer 1: return types, chained calls,
  inferred locals, framework conventions) before any language server is considered. A language
  server would need Java or Node on the target machine and is a separate decision.

## Consequences

- JavaScript and TypeScript resolved less often than Java until ADR-010, which added type resolution
  along call chains, Angular and React conventions, and template reading; `tests/test_web_frameworks.py`
  protects that and lists any new gap as a strict expected failure.
- Linking the whole codebase on every change is too slow for an editor; incremental re-linking of a
  changed file and the references to its symbols is required before the editor can write.
- Framework conventions (Angular decorators and templates, React components and hooks) are first-class
  requirements and belong in the parser and linker, not in the UI.
