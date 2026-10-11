# ADR-004: One SQLite library, background and resumable indexing

**Status:** accepted

## Context

A library may hold documents of thousands of pages whose meaning vectors take hours to compute on
an ordinary machine, and the app must stay usable meanwhile and survive being stopped.

## Decision

- **One SQLite file** (`data/library.db`) holds everything: documents, passages, the FTS5 full-text
  index, tables, cross-references, identifiers, meaning vectors (float16), collections and pins,
  search history, the code index, and the indexing queue. WAL mode lets readers carry on during
  writes. PDFs are stored beside it under their SHA-256, so a file is stored once.
- Schema changes are **additive**: `CREATE TABLE IF NOT EXISTS` plus a list of columns added since
  the first release (`_ADDED_COLUMNS`), applied on start. Old libraries open without migration steps.
- **Indexing runs in the background** on one worker thread with its own connection; the app's own
  connection is used by one call at a time. Jobs are also written to the library, so jobs an earlier
  run didn't finish are resumed when the app starts.
- A document is **searchable by words as soon as its pages are read**; vectors follow, saved every
  128 passages, so an interrupted run resumes from where it stopped and vectors from another model
  are replaced. Vectors are used only once a document's set is complete.
- Meaning vectors are kept in memory as one matrix and reloaded only when a version counter in the
  library changes, which every connection bumps when it changes vectors.
- Long tables also get a vector per run of rows, so a row deep in a table can be found by meaning.

## Consequences

- There is no server-side migration tool; a column is added by appending to `_ADDED_COLUMNS`.
- Everything is one process on one machine; nothing is designed for several users or machines.
- Memory for vectors is about 1.5 KB per passage; very large libraries are bounded by RAM.
