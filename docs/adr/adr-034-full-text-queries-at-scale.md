# ADR-034: Full-text queries on a very large document (amendment to ADR-004)

**Status:** accepted 2026-10-20; built the same day (roadmap step 24). Amends ADR-004 (one SQLite
library); ADR-033 stands.

## Context

Reported on 1.5.1 while testing with a standard of tens of thousands of pages: a search answers
fast, then the follow-up loads (opening a result, scoping to the document, the Related view)
deteriorate to "loading" for minutes. ADR-033 addressed the indexer sharing the process; this is
different, and it is in 1.5.0 and 1.4.0 too: it needs only a very large document in the library.

Every full-text query joins `blocks_fts` to `blocks` for the document, page, kind or provision
filters. Given a document filter, SQLite's planner chooses the `blocks` index for the document as
the outer loop and **runs the full-text match once per passage of that document** (`INDEX 0:=M1`
in the plan: match plus rowid). On a synthetic 5,000-page document (50,000 passages):

| Query | As written | FTS outermost |
|---|---|---|
| Search scoped to the document (`docs=`) | **171 s** | 0.1 s |
| Count of matches, scoped | 6.4 s | 0.02 s |
| `hit_pages` (every page view of a search result) | 4.6–7.1 s | 0.03 s |
| `_shared_terms` (Related view) | > 20 s | 0.07 s |
| `_similar_wording` (Related view) | 0.35–1.4 s | 0.11 s |
| Search unscoped | 0.5 s | 0.5 s |

The cost grows with the document (one full-text query per passage), so at 30,000 pages a scoped
search is a quarter of an hour, and every result opened costs a `hit_pages` of half a minute.
The unscoped search is fast because without a `blocks` filter the planner starts from the index,
which is why the first search looked fine and the next load did not.

A second, smaller fault on the same path: a search records itself in `search_history`, a write.
While the indexer's one transaction saves a very large document (minutes), that write waits the
connection's `busy_timeout` (15 s) and then fails with "database is locked", so every search in
that window takes 15 s and returns an error.

## Decision

1. **Every full-text query reads the index first.** `blocks_fts` is joined to `blocks` with
   `CROSS JOIN`, which SQLite honours as a fixed join order: the match runs once, and the document,
   page, kind and provision filters apply to its rows. A test takes the plan (`EXPLAIN QUERY PLAN`)
   of every statement the library runs against `blocks_fts` and requires it to begin with
   `SCAN blocks_fts`, so no query can return to the per-passage shape.
2. **Recording a search never waits for the indexer.** The history write is best-effort: it tries
   for a moment and gives up silently if the library is being written to; the search answers
   regardless. Other writes a user makes while the indexer saves (a pin, a note) keep the 15 s
   wait, and when it runs out the message says what happened: the library is being written by
   the indexer, try again in a moment.

## Measures

- The plan of every `blocks_fts` statement run by a document-scoped search, `hit_pages`,
  `page_matches`, the Related view's shared terms and similar wording begins with
  `SCAN blocks_fts` (the test fails on the queries as written today).
- On the 5,000-page synthetic document: the scoped search, `hit_pages` and the shared-terms query
  within a second each (numbers above), results unchanged (the existing search, page and Related
  tests).
- With another connection holding a write transaction, `record_search` returns within a second
  without an error, the search still answers, and a later search is recorded once the
  transaction ends. The locked message is the explanatory one.

## Consequences

- `src/search/library.py`: six queries gain `CROSS JOIN`; `record_search` lowers the busy timeout
  around its write and swallows the lock; `src/server/app.py` maps the locked error to its message.
- Release 1.5.2 carries it; the fix matters to any library with a document of thousands of pages,
  whether or not anything is being indexed.

## As built

- `src/search/library.py`: the six full-text statements (the scoped count, the ranked keyword rows
  — blocks and documents both `CROSS JOIN`ed, since the planner otherwise started from the
  one-row documents table — `hit_pages`, `_page_marked`, `_shared_terms`, `_similar_wording`)
  read the index first. `record_search` lowers `busy_timeout` to 250 ms around its write, swallows
  the lock and restores the 15 s wait (`_BUSY_TIMEOUT_MS`).
- `src/server/app.py`: `_error_message` turns SQLite's "database is locked" into "The library is
  being written to by the indexer (saving a large document); try again in a moment."

### Measures

- On the 5,000-page synthetic document (50,000 passages), after the change: search scoped to the
  document **171 s → 0.17 s**; document order, scoped 0.17 s; `hit_pages` 4.6–7.1 s → 0.04 s;
  `page_matches` 0.03 s; the Related view with a shared term (> 20 s before) 0.5 s; the unscoped
  search unchanged at 0.5–0.7 s.
- `tests/test_full_text_at_scale.py`: the plan guard reproduces the per-passage plan on the small
  fixture standard before the change (`SEARCH b USING INDEX blocks_doc_page` first) and passes
  after; the history write returns within 2 s against another connection's open transaction and
  the search still answers; the message.
- Every existing search, page view and Related test passes unchanged. Suite: **222 passed**, browser tests included.
