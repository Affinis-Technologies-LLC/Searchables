# ADR-020: Index snapshots, diffed

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 9, written
before building it).

## Context

A change to a codebase is usually read as a text diff. The index can describe it structurally:
which symbols were added or removed, whose signature or type changed, what moved, and which callers
of a changed or removed symbol are affected. That needs the index as it was before, kept as a
snapshot, and a comparison that works for a snapshot against the current index and for two
codebases indexed side by side (two checkouts of the same project).

## Decision

- **A snapshot** (`POST /api/codebases/{id}/snapshots`, with a label) copies the codebase's symbols
  (qualified name, kind, parameter count, signature, type, file, line, exported) and each symbol's
  linked caller count into `code_snapshots` / `code_snapshot_symbols`. It's cheap (one insert per
  symbol) and independent of git.
- **A diff** (`GET /api/codebases/{id}/diff?against=snapshot:N` or `against=codebase:M`) compares
  symbol sets by identity (kind, qualified name, parameter count):
  - **added** and **removed** symbols;
  - **changed**: same identity, different signature or type;
  - **moved**: same identity, different file;
  - for each removed or changed symbol, the **callers affected**: current linked callers of a
    changed symbol; for a removed one, the callers the snapshot counted and the current by-name
    references to its name (what the removal left unlinked);
  - **by-name count** then and now, so a change that made links uncertain shows.
- **In the Code panel**, a **Changes** segment: take a snapshot, pick a baseline (a snapshot or
  another codebase), see the four lists with the callers affected, each opening the code.
- Snapshots are kept until deleted; a codebase's removal removes its snapshots.

## Measures

- On a copy of the fixtures: add a method, change a signature, delete a method, move a file,
  rescan, diff against the snapshot: the four lists equal the hand-made ones (test).
- The same diff between two codebases (the fixture and its edited copy) gives the same lists.

## As built

`src/code/snapshots.py` (`take_snapshot`, `diff_against`), tables `code_snapshots` and
`code_snapshot_symbols`, routes `GET/POST /api/codebases/{id}/snapshots`, `DELETE /api/code/snapshots/{id}`,
`GET /api/codebases/{id}/diff?against=snapshot:N|codebase:M`, a **Changes** segment in the Code panel.
A symbol whose package changed shows as removed and added (identity is kind, qualified name and parameter
count); a file move within the same package shows as moved. Tests: `tests/test_snapshots.py`, the API test.

## Consequences

- Two tables, `src/code/snapshots.py`, three routes, a Changes segment.
