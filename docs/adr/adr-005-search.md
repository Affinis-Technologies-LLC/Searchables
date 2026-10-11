# ADR-005: Keyword and meaning search fused by rank, with measured thresholds

**Status:** accepted

## Context

Users search three ways: exact words and phrases, questions in their own words, and identifiers.
Each needs a different engine, and the results must say how they were found.

## Decision

- **Keyword search** is SQLite FTS5 with Porter stemming; the query syntax (`"phrase"`, `OR`,
  `-word`, `prefix*`) is turned into a safe FTS5 query. Using any of that syntax means "exactly these
  words", and switches meaning search off for that query.
- **Meaning search** embeds the query with the local model and takes the nearest passages above an
  absolute floor and within a band of the best match. Acronyms from the documents' own lists are
  spelled out for it.
- The two are merged by **reciprocal rank fusion**; when few passages contain every word, passages
  containing some of them are listed after those. Every result says how it matched: words, some of
  the words, meaning, or both.
- **Identifier search** is exact on a normalised key (case, spaces and hyphens ignored), grouped by
  role (introduced, table rows, rules, mentions), with related identifiers from shared rows and passages.
- **Related passages** come from fixed sources in order: references, shared identifiers, same topic by
  meaning (with rule-based findings), defined terms, similar wording.
- Thresholds live in `src/config.py` and are to be set on evidence: `python -m src.evaluate` scores
  words, meaning and both against the user's own expected results.

## Consequences

- No result can appear without a stated reason, and no result is generated.
- Threshold changes are a measurement exercise, not a matter of taste; the evaluation set is the
  user's, kept out of the repository.
