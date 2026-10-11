# ADR-003: Rule-based, explainable extraction, discovered per document

**Status:** accepted

## Context

Standards differ in layout: ISO clauses, military-standard appendices numbered in tens, run-in
headings, tables continued over pages, identifiers of every shape. The tool must read any of them
without being told the format, and a user must be able to see why it read something the way it did.

## Decision

- Pages are read with PyMuPDF (text, blocks, ruled tables, drawings); scanned pages with Tesseract
  when present. Each text block becomes one passage, tagged with its clause, printed page and position.
- Structure is **discovered from the document itself**, by rules with thresholds in `src/config.py`:
  clause headings (bookmarks first, then numbering patterns that only move forward), running headers
  and footers (repeated in the margins), printed page numbers, tables and their captions, figures by
  their captions, cross-references, defined terms, acronym lists, the distribution statement.
- **Identifiers are discovered, not configured.** Tokens mixing letters and digits, labelled numbers
  and numbered pairs are grouped into families by shape; a family counts as identifiers when it has
  several distinct values across several passages. The user can switch families on or off per
  document, and the choice survives re-indexing.
- Provisions (shall / should / may / note) come from the verbal form; list items inherit their lead-in's.
- Nothing is hard-coded to one document or one standard, and the repository names none (ADR-008).
- Every extractor change that changes results bumps `EXTRACTOR_VERSION`; documents record the version
  that indexed them, and the app offers to re-index older ones. The health report in Library →
  Manage says what the extractor found and flags what it may have missed.

## Consequences

- Precision is bounded by the rules; the trade is that every outcome can be traced to a rule and a
  threshold, and tuned there.
- Rules are tested on made-up PDFs built in the tests (`tests/conftest.py`), never on real documents.
- A new document convention is added as a rule plus a test, not as a special case for one document.
