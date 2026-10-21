# ADR-033: Searching while a large document is indexed (amendment to ADR-004)

**Status:** accepted 2026-10-20; built the same day (roadmap step 23). Amends ADR-004 (background
indexing) and ADR-007 (calls take turns); both stand.

## Context

Reported after 1.5.0: with a standard of tens of thousands of pages being indexed, every search is
extremely slow, and nothing on screen says why. The cause is not the index: keyword search over a
synthetic library of 300,000 passages answers in 0.2–0.8 s, and nothing in 1.5.0 touched the search
path. The cause is the indexer sharing the process with the searches, in four ways that the records
so far do not address.

1. **A search waits for the model behind the indexer's batch.** The embedding model is used by one
   caller at a time (`semantic._encode_lock`); the indexer reads passages eight at a time and lets a
   waiting search go first *between* batches (ADR-004). Measured on this machine (8 threads): one
   batch of eight long passages takes 2.3–2.9 s, so a search's query vector waits 1.2–2.4 s, and up
   to 5 s when the machine is loaded. Every search by meaning, and every Related view (its
   assessment embeds sentences), pays this.
2. **The wait is paid under the API lock.** Calls take turns under `services.lock` (ADR-007) for the
   whole handler, including the model wait, so while a search waits, the `/state` poll that feeds
   the status bar waits too. The progress display freezes exactly when the user wants it: the app
   looks hung rather than busy.
3. **The indexer takes every core.** PyTorch runs the model on all hardware threads; the server
   thread and the browser compete with it for the rest of the time.
4. **Long stages are silent, and a resumed job says nothing.** After the last page is read, the
   clause, cross-reference and identifier passes and the write of every passage into SQLite and FTS
   report no stage: the status bar sits at "reading pages N of N" for minutes on a large document.
   A job left unfinished when the app stopped (a service restart, the 1.5.0 upgrade re-pointing the
   service) is resumed at start-up without saying so; a document stopped while its pages were being
   read is read again from the first page. The user sees the app "automatically restarting" work
   with no explanation. Nothing is logged.

Measured alternatives for the batch (48 long passages, searches arriving every second):

| Indexing batch | Throughput | A search's wait for the model |
|---|---|---|
| 8 passages (as now) | 1.8–3.5 /s | 0.9–2.4 s |
| 4 passages | 3.3–4.2 /s | 0.1–0.8 s |
| 2 passages | 2.9–3.9 /s | 0.1–0.5 s |

The batch of four costs nothing in throughput and more than halves the wait. Four model threads
instead of eight cost nothing either (3.1 against 3.0 passages/s); two threads halved throughput.

## Decision

1. **The indexer reads four passages at a time** (`EMBEDDING_BATCH` 8 → 4), so a search waits at
   most one short batch; a waiting search still goes first between batches.
2. **The model wait leaves the API lock.** A search's query vector is computed before the lock is
   taken, and `Library.search` accepts it ready-made; the status bar's `/state` is answered while a
   search waits for the model. The Related view's sentence embedding stays under the lock, bounded
   by the shorter batch.
3. **The model keeps half the machine**: PyTorch is limited to half the hardware threads, at least
   two, when the model loads, leaving the server and the browser their share.
4. **Every stage reports**: after *Reading pages* come *Finding clauses and tables*, *Finding
   cross-references*, *Finding identifiers* and *Saving passages*, each with its count, before
   *Understanding passages*. A job resumed at start-up is reported as such (`resumed` in `/state`)
   and shown as "Resuming" with what that means for an add stopped during reading ("read again
   from the first page"). The Search view shows one line while a job runs: what is being indexed
   and that searches answer more slowly until it is done.
5. **Keyword results are ranked before they are highlighted**: `highlight()` and `snippet()` run
   on the rows kept, not on every matching row (0.6–0.8 s → 0.4 s on the heaviest query at 300,000
   passages). Same results, same order.

Not done, and why: indexing in a separate process (would end the model and lock contention
entirely, but needs a second copy of the model in memory and a new progress channel; the measures
above show the shared process can be made acceptable first); resuming page reading mid-document
(the extractor needs the whole document for running headers and the outline; ADR-004's "searchable
once its pages are read" stands); a log file (the Library's Jobs list and the status bar are the
record; revisit if a resumed job is still a mystery after item 4).

## Measures

- `semantic.embed_passages` hands the model four passages at a time; a query that arrives during a
  run of passages is encoded before the next batch (test with a recording stand-in for `_encode`).
- `/state` answers while a search is waiting for the model (test: the query embedding blocked on an
  event in one thread; `/state` returns before the event is set).
- The thread limit: `semantic.indexing_threads(cores)` is `max(2, cores // 2)`, and the model is
  loaded with it.
- The extraction progress callback sees the stages in order with their totals on the fixture
  standard; `/state` carries `resumed` for a job left by an earlier run; the status bar and the Jobs
  list say "Resuming".
- On a synthetic 5,000-page PDF (50,000 passages, 45,000 cross-references): pages read in 47–58 s,
  then 11 s of silent passes (clauses, cross-references, identifiers) and a few seconds' store, so
  about a fifth of extraction shows no progress today; the first search after the add 0.11 s; the
  glossary's one-time load of the passages 0.6 s. Scaled to 30,000 pages: some six minutes reading,
  a minute silent. Embedding is the long part: 300,000 passages at 3.5/s is about a day, during
  which every item above applies.
- The reported case: with the tens-of-thousands-page standard being indexed, a search by meaning
  answers within one batch (under 1 s plus the search itself), the status bar keeps moving, and
  the Search view says what is running. To be confirmed by the owner on the machine concerned.

## Consequences

- `src/config.py` (`EMBEDDING_BATCH`), `src/search/semantic.py` (thread limit at load),
  `src/search/library.py` (`search(query_vector=…)`, the ranked-first keyword query),
  `src/server/app.py` (the search handler embeds outside the lock; `resumed` in `_job`),
  `src/extractor/pdf.py` and `library._store_extraction` (stage callbacks), `src/search/indexer.py`
  (stage names), the status bar, the Jobs list and the Search panel's notice; Help's Library page
  says what to expect while a large document is indexed.
- Indexing a very large document still takes hours on an ordinary machine (ADR-004); this record
  makes the app usable and honest meanwhile, not faster.

## As built

- `EMBEDDING_BATCH` 4 (`src/config.py`); `semantic.indexing_threads(cores)` = `max(1, min(cores,
  max(2, cores // 2)))`, applied with `torch.set_num_threads` when the model loads.
- `PDFExtractor.extract` reports `Reading pages`, `Finding clauses and tables` (every 200 pages),
  `Finding cross-references` (every 5,000 passages) and `Finding identifiers`; `_store_extraction`
  reports `Saving passages` before and after its one transaction; `Understanding passages` as
  before. The extractor's callback now takes `(stage, done, total)`, the same shape as the library's.
- `Library.wants_query_vector(query, scope)` says whether a search would read the model (vectors to
  search, model present, no answer kept); `Library.search(..., query_vector=)` takes the vector
  ready-made. The `/search` handler takes the lock for the acronym expansion, embeds outside it,
  and takes it again for the search. `_keyword_rows` ranks in a subquery and highlights the rows
  kept.
- `Job.restarted`: a resumed add whose document isn't in the library yet (stopped during reading).
  `/state` carries `resumed` and `restarted`; `web/src/shell/jobs.ts` (`jobTitle`, `jobProgress`,
  `indexingNotice`) feeds the status bar, the Library's Jobs list and the Search view's notice.
  Help's Library page describes the stages, the resumed job and the slower searches meanwhile.

### Measures

- `tests/test_indexing_while_searching.py`: ten passages reach the model as 4, 4, 2; a query arriving
  during a run of 24 passages is encoded before the next batch (position ≤ 3 of 7 calls); the
  thread share for 1, 2, 3, 4, 8, 16 cores is 1, 2, 2, 2, 4, 8; the fixture standard reports the six
  stages in order, each ending at its total; a job left before its pages were read is `resumed` and
  `restarted`, one left during its vectors is `resumed` only.
- `tests/test_server.py`: with the query embedding blocked in one thread, `/state` answers in under
  2 s while the search is still waiting, and the search then completes with results; `_job` carries
  both flags. `web/src/shell/jobs.test.ts`: the three labels.
- Keyword results unchanged: every existing search test passes against the ranked-first query.
- Suite: **219 passed** (216 plus the three browser tests); Vitest and `tsc` clean; bundle rebuilt.
- Still owed: the reported case on the machine concerned — a search by meaning while the large
  standard is indexed, the bar moving, the notice shown — to be confirmed by the owner. The
  Windows measure of the thread share (this one was on an 8-thread Mac).
