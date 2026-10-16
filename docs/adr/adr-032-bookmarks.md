# ADR-032: Bookmarks audited, rebuilt and reported (amendment to ADR-031)

**Status:** accepted 2026-10-16 (drafted and agreed in one step at the owner's request, as ADR-031
was); built the same day (roadmap step 22). Amends ADR-031's bookmark handling; ADR-031 stands.

## Context

A PDF's outline (its bookmarks) is not decoration in this tool: `HeadingDetector`
(`src/extractor/structure.py`) **trusts the outline first** and uses numbered-heading patterns only
for the clauses the outline omits. A correct outline therefore improves what the library knows of
a document — Contents, clause paths in citations, the References resolution, the Catalogue's
"where" — and a wrong one misleads it. ADR-031 finds bookmarks whose destination is *gone*; it
does not find a bookmark that points at the wrong page, nor the clauses that have no bookmark at
all, nor does it offer to write the outline a document lacks. Standards often arrive with no
outline, or one that stops at chapter level, and readers outside Searchables navigate by it.

## Decision

Three additions, all deterministic, all from the headings the extractor already finds.

### 1. Bookmarks audited the way links are

Each bookmark is matched to a heading: by its normalised text first ("5.2 M 12.6 Summary
message"), else by its clause number when it has one. Its state:

| State | Meaning | Proposed fix |
|---|---|---|
| **ok** | resolves, and the matched heading is on that page | none (a differing title is offered as a retitle, see below) |
| **wrong page** | resolves, but the matched heading is on another page | re-point to the heading |
| **dead** | the destination is gone; a heading matches | re-point to the heading |
| **unresolved** | the destination is gone; no heading matches | none; listed |
| **unchecked** | resolves; no heading matches the title (front matter, a title the extractor doesn't see as a heading) | none; left as it is |

A bookmark matched by number whose title differs from the heading's text gets a **proposed
title** (the heading as printed), applied with the fix; it is counted as *retitled*, not as a
state. **Headings without a bookmark** are listed with their page.

### 2. The outline rebuilt from the headings

An option in the Links view, off by default: **Rebuild the bookmarks from the N headings**. The
fixed file's outline is then written whole from the extracted headings in reading order — clause
number and title, level from the number's depth (annexes at level 1, their clauses beneath),
unnumbered headings at level 1, each pointing at the heading's top-left — **replacing** the
existing outline. Replacing, not merging: a merged outline would carry the old one's errors and
duplicates, and the headings are the better source whenever the audit shows the old outline
wrong. Levels are made consistent (a jump of more than one level is clamped, as PDF readers
require). When the option is on, the per-bookmark fixes are moot and are not applied.

### 3. A health check in the Library

The document's extraction report (`Library.health`, "Manage" in the Library view) gains one row,
**Bookmarks**: how many the stored PDF has against the clauses found, how many point at the wrong
page, how many clauses have none. It **warns** only when bookmarks disagree with the headings:
a document with no outline is common and the detector copes, so "none" carries a note ("the Links
view can add them from the N clauses found") and no warning. The same matching serves the audit
and the check, so the two never disagree.

## Measures

- The ADR-031 fixture gains a bookmark to the wrong page ("5.1 M3.2 Status message" pointing at
  page 1) and one with a title the extractor doesn't know ("Front matter" on page 1): states
  wrong page → 2, unchecked; the dead one as before → 3; `unbookmarked` lists the headings with
  none. The fixed file's outline has the re-pointed pages.
- A rebuilt outline on the fixture: every heading, levels 1 and 2 as the clause numbers say, each
  landing on its heading's page; the old entries gone; the file re-checked shows every bookmark ok
  and no heading without one.
- `Library.health` on the fixture standard (no outline): "none", no warning; on the broken fixture
  added to the library: the wrong-page count, warned.
- The API test downloads with `outline=1`; the browser test sees the bookmark states and the
  rebuild tick.

## Consequences

- `src/extractor/structure.py` gains `match_outline(toc, headings)` — the one matching used by
  `links.check` and `Library.health`; `src/research/links.py` gains the states, `proposed_title`,
  `unbookmarked`, `outline_from_headings` and the `outline` option of `fixed`; the download route
  takes `outline=1`; the Links panel shows the bookmark states, the retitles, the unbookmarked
  headings and the rebuild tick; the Library's Manage report gains the row; Help's Links page says
  so.
- Not done: bookmarks for tables and figures; merging outlines; using outlines for edition
  comparison (Compare pairs by headings, a superset).

## As built

- `src/extractor/structure.py`: `match_outline(toc, headings)` → one `OutlineMatch` per bookmark
  (the heading it names by normalised text, else by clause number, with `by_number` set) and the
  headings nothing names. `src/extractor/pdf.py`: `destination_of` (moved from `links.py`, since the
  Library needs it too) reads a link's or outline item's destination at the raw object level.
- `src/research/links.py`: bookmarks get the states of the table above plus `unchecked`;
  `proposed_title` when matched by number; `Report.unbookmarked`; `outline_from_headings` (levels
  from the clause numbers, a jump clamped to one, each entry at its heading's top-left);
  `fixed(..., outline=True)` writes it whole, else applies the re-points and retitles. The route takes
  `outline=1`.
- `Library.health` gains the **Bookmarks** row from the stored PDF's outline: "none" with the note
  that the Links view can add them, or "N for M clauses" with the wrong-page, gone and
  without-bookmark counts; warned only when any point wrong or are gone.
- The Links panel: bookmark states and the retitle line, "Headings without a bookmark" with Show,
  the rebuild tick (naming how many existing bookmarks it replaces), the summary counting retitles.
  Help's Links page says so.

### Measures

- The ADR-031 fixture now carries five bookmarks: ok, unchecked ("Front matter"), ok, wrong page
  (→ 2), dead (→ 3); two headings without one ("3 DEFINITIONS", "3.1 Acronyms and abbreviations").
  The fixed outline has pages 1, 1, 2, 2, 3; re-checked, every bookmark is ok or unchecked.
- A bookmark titled "5 Detailed requirements (old title)" is matched by number, kept ok, and
  retitled "5 DETAILED REQUIREMENTS" in the fixed file.
- Rebuilt from the headings: six entries, levels 1/1/2/1/2/2 as the numbers say, each on its
  heading's page; re-checked, all ok and nothing unbookmarked; every page's text unchanged.
- `Library.health`: the plain fixture reads "none", not warned, "the Links view can add them from
  the 6 clauses found"; the broken fixture reads "5 for 6 clauses", warned, "1 points at the wrong
  page; 1 whose destination is gone; 2 clauses have none".
- Suite: **212 passed**, browser tests included.
