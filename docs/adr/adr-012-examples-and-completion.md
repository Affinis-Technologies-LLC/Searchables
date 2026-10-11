# ADR-012: Examples as you type, and completion from the index

**Status:** accepted 2026-10-11; built the same day (roadmap step 3). On the judged set
(`tests/examples_set.json`, 14 contexts on the fixture codebase) precision@3 is 0.667 for Java and
TypeScript against 0.556/0.533 for the unranked candidates and 0.185/0.267 for text search; MRR 1.0
against 0.82/0.80 and 0.24/0.39. A context request on the 3,000-file corpus takes 5–10 ms warm
(about 2 s for the first, which loads the linker state); examples 1–85 ms, "methods like this one"
bounded at 20,000 reference rows.

## Context

ADR-001's second layer is the assistant itself: as a developer writes code in the editor, the tool
shows real snippets from the codebase that do the same kind of thing, ranked so that a compatible,
well-chosen example comes first, with its file and lines, and offers completion drawn from the index
rather than from the text of the buffer. Nothing is generated; every example is a passage that exists.

What's in place: the index resolves most expressions' types without a compiler (ADR-010), and the
editor holds an unsaved buffer that is parsed only when saved (ADR-011). The inspector describes the
**saved** file; the examples must describe the **unsaved** one, at the cursor, while it's being typed.

What's missing is an honest measure. ADR-001 names an evaluation set: recorded typing contexts with
the examples a developer judged useful. Without it, ranking changes are opinion. This ADR makes the
record the first deliverable and the ranking the second.

## Decision

### 1. The context: what's being written

- On every pause in typing (about 400 ms) and on cursor moves between expressions, the browser sends
  the **buffer, the cursor and the file id** to `POST /api/code/files/{id}/context`. Nothing is
  written to disk; the buffer is parsed in memory with the same tree-sitter parser as the index.
- The server answers with the **context**: the enclosing symbol (its kind, qualified name, type and
  package); the **expression under construction**, as the parser sees it with the cursor inside
  (receiver chain, the partial member name, the arguments so far, whether it's a call, a `new`, a
  type position, a JSX tag or a decorator); the receiver's **resolved type**, with the same certainty
  labels as everywhere (resolved, supertype, by name); the enclosing method's **neighbours** (the
  calls, types and identifiers already in it, and the statement kinds around the cursor); and the
  file's imports.
- Resolution of the unsaved buffer uses the warm linker state of ADR-011 (symbols and imports of the
  rest of the codebase) plus the buffer's own declarations; it never touches the stored index.
- A buffer the parser can't fully read still gives a context: tree-sitter's error recovery keeps the
  enclosing nodes, and the expression is taken from the tokens before the cursor when no node fits.

### 2. Candidates: a hard filter before any ranking

The examples are **call sites and constructions already linked in the index** (`code_refs` with a
target or an outside API name). A candidate must pass one of these, in order; the first that yields
anything is used and reported:

1. **Same member on the same resolved type** (or a supertype or interface of it): references whose
   target is that member.
2. **Same member name on the resolved type's siblings** (types sharing a supertype), when 1 gives
   nothing.
3. **Same member name on any type, or the same outside API**, flagged as by-name.
4. **Nothing resolves** (no receiver, or the name is new): references whose enclosing method is
   most like the current one by neighbours (see `C` below), so the panel still shows "code written
   in a place like this".

Never: the line being written, the current method's own references, generated or vendored code
(folders the scan skips are never indexed anyway), or more than one example per enclosing method.

### 3. Ranking: deterministic, explained, tunable by hand

The score is ADR-001's weighted sum, each feature in [0, 1]:

| Feature | Weight | How it's computed |
|---|---|---|
| Type compatibility `T` | 0.30 | Same receiver type 1.0; supertype or interface 0.8; sibling 0.5; same name elsewhere 0.3; outside API with the same name 0.3 |
| Symbol similarity `M` | 0.25 | Same member 1.0; same member on a sibling 0.7; an overload (same name, other arity) 0.5; same name, unrelated 0.2 |
| Context similarity `C` | 0.20 | Jaccard overlap between the sets of {calls, types, identifiers} in the two enclosing methods |
| Structural similarity `P` | 0.15 | Similarity of the statement-kind sequences in a window of five statements around each call (longest common subsequence over tree-sitter node kinds, over the window length) |
| Example quality `Q` | 0.10 | 1.0 for a complete statement of one to three lines whose receiver and arguments are resolved; less for very long statements, unresolved parts, or a line that's mostly a string; test code counts as good, not bad |

Weights live in `src/config.py` (`EXAMPLE_WEIGHTS`) and in the response, so the panel can say *why*:
each example carries its feature values and a one-line reason ("same `UserRepository` method, called
from a service like this one"). Ties break by recency of nothing (there's no git yet, ADR-015) and
then by path, so results are stable between calls.

**No learning in the loop.** The developer's actions on examples (previewed, went to, inserted,
dismissed) are **recorded locally** in a table `example_feedback` (context digest, candidate,
action, time) and exported with the evaluation set; the weights are changed by hand against them.

### 4. Completion from the index

Monaco's completion provider for Java, TypeScript and JavaScript is backed by `GET
/api/code/files/{id}/complete` on the same context:

- after a receiver (`repo.`): the resolved type's **members** (and inherited ones), each with its
  signature, type, and the **count of examples** in the codebase;
- otherwise: symbols in scope in the buffer (locals, parameters, fields of the enclosing type),
  then the file's imports, then **importable top-level symbols** of the codebase by prefix
  (inserting adds the import, Java and ES modules alike);
- never words from the buffer's text, and never anything the index doesn't know.

Monaco's own word-based suggestions are turned off for these languages so that what's offered is
always something real.

### 5. The Examples panel

A third pane beside the inspector (or a tab of it on narrow screens), updating with the context:

- the context line ("`userRepository.find` on `UserRepository`, in `UserService#load`", with the
  certainty of the receiver's type);
- the examples, each with path and lines, the statement highlighted inside three lines of its
  method, the score, the reason, and **Preview · Go · Insert**. Preview shows the whole enclosing
  method read-only; Go opens it in a tab; Insert puts the statement at the cursor **as written**
  (no renaming of variables; ADR-001 leaves adaptation open);
- a **dismiss** that hides the example for this context and records the action.

### 6. The evaluation set and the measure

- `python -m src.evaluate_examples <set.json>` runs recorded contexts (file text, cursor, codebase
  root) through the same code and reports **precision@3** (the share of the top three the judge
  marked useful) and mean reciprocal rank, per language, against two baselines: plain text search
  for the member name, and candidates in path order without ranking.
- The set is built by hand: `src.evaluate_examples --record` appends the current context and the
  top ten candidates to a file for a judge to mark. Thirty contexts per language is the floor.
- The step is done when precision@3 beats both baselines on the set, and the set is in `tests/` for
  the fixture codebases (judged by whoever builds the step, with the judgement explained in the file).

## Options considered

- **Ranking by text similarity alone (BM25 over statements).** The baseline; it can't tell a
  `find` on a repository from a `find` on a string. Kept as the fallback and the measure's baseline.
- **Learning the weights from the feedback automatically.** Small data, opaque results, and a
  system that behaves differently on each machine. Hand-tuned weights, recorded reasons.
- **Parsing the buffer in the browser** (tree-sitter's WebAssembly build). Would save a round trip
  but duplicate the parser, the rules and the linker state in a second runtime. The server parses.
- **Examples from outside the codebase** (library sources, documentation). Nothing to index them
  from, and the point is *this* codebase's practice.
- **A language server for completion.** ADR-001 defers it; completion here is from the index and is
  measured as such.

## Measures

- A context request on the 3,000-file corpus answers in under 150 ms on the server (parse the
  buffer, resolve the expression, select and rank up to 200 candidates).
- Every candidate shown passed the filter it claims; a unit test per filter and per feature.
- precision@3 and MRR on the evaluation set, per language, above both baselines.
- The feedback record is local, appendable, and exported with the set.

## Consequences

- The server parses unsaved buffers: more CPU while typing, bounded by the pause and by one
  in-flight request per file (the browser drops a stale one).
- The index gains `example_feedback`; `src/config.py` gains `EXAMPLE_WEIGHTS`; `src/code/` gains
  `context.py` (the buffer's context), `examples.py` (filter and rank) and `complete.py`.
- Three panes in the Code view: layout work in `web/`, with unit tests for the panel's state
  (current context, dismissed examples, in-flight request handling).
- The quality of examples is bounded by resolution (ADR-010); the panel always shows the receiver's
  certainty, so a by-name context is seen as such.

## As built

- `src/code/context.py`: the expression under construction is read from the text before the cursor;
  the member being typed is replaced by a sentinel call and the buffer parsed, so the parser's own
  rules give the receiver chain and the linker's `_follow` the type. Fields declared only in the
  buffer resolve from their declared type. Neighbours are the enclosing method's calls, types and
  identifiers; the statement shape comes from the sentinel's statement.
- The parser records for every call and construction the kinds of the statements around it
  (`code_refs.shape`, letters with the statement itself in upper case) and the statement's lines;
  an index from before these columns is re-read on the next rescan. Per-method locals are kept in
  `ParsedFile.locals` for completion.
- `src/code/examples.py`: the filters in the order decided, with one change: siblings are added when
  the type itself has fewer than three examples, not only when it has none. An outside API with
  the same owner and member (`axios.get`, the platform's `fetch`) counts as the same member (T 1.0,
  M 1.0), not as "same name" (0.3): it's the same API. Platform globals (`fetch`, `console`, `JSON`,
  `document`…) are now linked as `#name` by the script linker so this works; before, they were left
  by name.
- `C` uses the enclosing methods' calls, types and constructions (identifiers aren't indexed per
  method); `P` is the LCS over the shape letters; `Q` as decided, with "mostly a string" measured over
  the statement's text.
- `src/code/complete.py`; `src/evaluate_examples.py --show`; `example_feedback` in the store; routes
  `POST /api/code/files/{id}/context`, `…/complete`, `POST /api/code/feedback`.
- Front end: an **Examples** view in the inspector (the Code view keeps three panes; the inspector
  switches to Examples on the first keystroke and back to Usages when a symbol is followed), state
  in `web/src/code/assistant.ts` (unit-tested), the panel in `ExamplesPanel.tsx`, completion as a
  Monaco provider with Monaco's word suggestions off, imports added as additional edits.
- Monaco 0.52 note: disposing a diff editor takes services other editors' suggest widgets still
  use, so the comparison view keeps one diff editor for the app's life (ADR-011's Compare).

## Open questions

- Should examples also come from the **documents** (a Catalogue identifier typed as a string shows
  the rule)? Natural, but that's step 5 (ADR-014); here, no.
- Should Insert adapt variable names to the ones in scope? As-is first, per ADR-001.
- How many examples: five shown, more on request, up to twenty.
