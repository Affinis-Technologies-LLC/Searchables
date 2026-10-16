# ADR-031: Fixing a PDF's dead links

**Status:** accepted 2026-10-16 (drafted and agreed in one step at the owner's request: "there are
no external links, draft ADR-031 and implement this"); built the same day (roadmap step 21).
Amended by ADR-032 the same day: bookmarks audited like links, the outline rebuilt on request, a
health row in the Library.

## Context

The standards the library holds are PDFs whose internal links — "see TABLE 5.1-2", "4.2.3",
"Annex A", the bookmarks panel — break when the document is re-assembled, pages are removed, or
an edition is produced from an older one: the link annotation survives but its destination is a
page object that no longer exists, a named destination nobody defines any more, or simply the page
where the table *used* to be. Readers click and land nowhere, or on the wrong page. The documents
in question carry no external URLs; the links are all internal.

What the repository already has is most of the fix. The extractor finds every cross-reference in
the text with its kind and target (`find_xrefs`, ADR-003) and knows where every clause, table,
figure and annex is (`TextBlock.clause_num`, `label`, `page`, `bbox`); the inspector's References
view resolves a reference to its page and box today. PyMuPDF reads and writes link annotations
and the outline. Nothing in this is a model or a guess: a reference is parsed by rule, resolved by
the document's own structure, and a link is rewritten to point there.

Tried before writing this (PyMuPDF 1.28.2 on the fixture standard):

- a GoTo annotation whose `/Dest` names an object that doesn't exist is reported by
  `page.get_links()` as **page 1** — silently. Dead destinations have to be found at the raw
  object level (`/Dest`, `/A /D`), not through the convenience API;
- a named destination with no entry is reported as `nameddest` and is absent from
  `resolve_names()` — detectable;
- a bookmark to a removed page comes back from `get_toc()` with page `-1`;
- deleting a link and inserting a GoTo to a page and point, then saving, keeps every page's text
  intact.

## Decision

### Its own experience: the Links view

A new view in the activity bar, **Links**, separate from the library: the user drops a PDF, reads
a report, unticks what they don't want changed, and downloads the fixed PDF. The uploaded file is
**not added to the library** (a tick offers to add it afterwards, through the ordinary add); it is
held in the server's memory under a token for the session and dropped when a newer upload replaces
it or the server stops. Nothing is written to disk.

### What is checked

The document is extracted with the library's own extractor (headings, objects, cross-references;
no indexing, no embedding), and every link annotation and bookmark is classified:

| State | Meaning | Proposed fix |
|---|---|---|
| **ok** | GoTo or named destination that resolves to a page, and the reference text under the link (if any) is on that page | none |
| **dead** | the destination object or name doesn't exist | re-point to where the reference text resolves |
| **wrong page** | the destination resolves, but the text under the link is a reference the document locates on another page | re-point there |
| **unresolved** | dead or wrong, but the text under the link is not a reference the extractor can place (or names another standard) | none; listed for a person |
| **external** | a URI link | none; reported, never checked (the app is offline) |

The **text under a link** is the words of the line the link rectangle covers, so "TABLE 5.1-2"
is read whole when only "5.1-2" is underlined; of the references found on that line, the one whose
number lies inside the rectangle is the link's. The resolution is the library's rule (ADR-003):
a table or figure by its label (or its caption), a clause or annex by its number, the heading
preferred over the first passage; the target point is the block's top-left.

**Bookmarks** whose page is gone are matched by title against the extracted headings (number and
title, whitespace and case folded); matched ones are re-pointed, the rest listed as unresolved.
Healthy bookmarks keep their destination as it was.

**Unlinked references** — text the extractor recognises as a reference with no link annotation
over it — are listed with a count and offered as an option, off by default: *add links for them*.
It is the same rewrite, applied to text that never had a link.

### What is refused, and what is not promised

- A PDF that needs a password, one whose permissions forbid annotation changes, and one carrying a
  digital signature (any change would invalidate it) are refused with the reason. Nothing is
  rewritten silently.
- The file is saved by PyMuPDF, so it is not byte-identical: objects are renumbered and streams
  recompressed. What is promised, and tested: every page's text is the same before and after, and
  only link annotations and the outline differ. Form fields, other annotations and metadata are
  untouched.
- External URLs are not checked: the app has no network by design (ADR-002). The documents in
  question have none; if one appears it is listed as external.
- A reference the extractor cannot place stays as it is. The tool does not guess a page.

### The API

- `POST /api/links/check?filename=` with the PDF as the body → the report: a token, the page
  count, refusal (if any), the links (page, rectangle, text, state, target as found, proposed
  page and box, an id), the bookmarks likewise, the unlinked references, and counts per state.
  Synchronous: extraction of a long standard takes seconds, shown as "Checking…".
- `GET /api/links/{token}/pages/{n}` → the page as a PNG at a fixed scale, for the report's
  "Show" beside each link (the view draws the rectangle; the file isn't in the library, so the
  PDF viewer isn't used).
- `GET /api/links/{token}/fixed?skip=<ids>&add=1` → the fixed PDF as a download, named
  `<original> (links fixed).pdf`, with the proposed fixes applied except those skipped, and the
  unlinked references linked when `add=1`. A CSV of the report is offered from the view.

## Measures

- A fixture PDF with one link of each kind, made the way a bad merge makes them: a GoTo whose
  `/Dest` names a missing object, a named destination nobody defines, a GoTo to the wrong page
  under "TABLE 5.1-2", a healthy GoTo, and a bookmark to a page that no longer exists. The report's
  states equal the hand list; the fixed file re-checked has every link ok; every page's text is
  identical before and after; the bookmark lands on its heading.
- The three refusals (password, no annotation permission, signature flag) each refuse with the
  reason.
- The unlinked-references option adds a link over "TABLE 5.1-1" in the fixture's text and nowhere
  over text that already carries one.
- The API test uploads the fixture and downloads the fixed file; the browser test opens the Links
  view, drops the fixture, sees the states and the download link.
- On a real standard with broken links (the owner's): links found, by state, and fixed; seconds
  per hundred pages. Recorded when run.

## Consequences

- `src/research/links.py` (the checker and the fixer), three routes, `web/src/documents/LinksPanel.tsx`
  with a `links` activity, a Help page for the view, the API and browser tests.
- A new kind of output: the app produces a modified PDF for download. It never changes the uploaded
  file or a library copy in place, and the result is offered to the browser that sent the file —
  nothing leaves the machine (ADR-002, ADR-008).
- PyMuPDF's share of the program grows (ADR-029 unchanged: it was already the PDF reader).
- Not done: fixing links *between* documents (a PDF can't link into the library), checking
  external URLs, and any change beyond link annotations and the outline.

## As built

- `src/research/links.py`: `check(file_bytes, filename, extractor)` → `Report`; `fixed(file_bytes,
  report, skip, add)` → the PDF; `page_image` for the view. Destinations are read from each
  annotation's `/Dest` or `/A` (`_destination`): an array whose first element is an object
  reference is checked against the page objects, an integer against the page count, a string or
  name against `resolve_names()`; `/URI` actions are external. The same function classifies the
  outline items, because `get_toc()` reports a bookmark to a missing page object as page 1, exactly
  as `get_links()` does for a link (both confirmed by the fixture's first test). The text under a
  link is the words its rectangle covers, punctuation stripped, and the line those words sit on
  gives the candidates (`find_xrefs`); the candidate whose number lies in the link's own words is
  the reference. Placement mirrors `Library.resolve` over the `ExtractedDocument` in memory. Fixes
  are applied per page with all deletions before any insertion and a page reload between, because
  PyMuPDF's link list on a page loses its xrefs once something has been inserted — found while
  building and recorded here rather than worked around silently.
- Refusals: `needs_pass`, `permissions` without `PDF_PERM_ANNOTATE` (an owner-password PDF opens
  without a password yet forbids the change: this is the case the permission bit catches), and
  `get_sigflags() > 0`.
- Routes: `POST /api/links/check?filename=`, `GET /api/links/{token}/pages/{n}`, `GET
  /api/links/{token}/fixed?skip=&add=`. The server keeps the last three uploads in memory under
  their tokens (`services.link_checks`); the download is named `<stem> links fixed.pdf` (the
  download helper strips parentheses from file names).
- The view: a `links` activity, `web/src/documents/LinksPanel.tsx` (the drop zone, the counts, the
  fixes to be applied with a tick per link, the groups by state with Show and Target, the
  bookmarks, the unlinked references with the add-links tick, Download and CSV) and a `links` tab
  kind whose view shows the page as an image with the link outlined, with page stepping.
  `docs/help/links.md` is the view's Help page.
- Tests: `tests/test_links.py` (six), `test_fix_links_api` in `tests/test_server.py`,
  `test_fix_a_pdf_s_links` in `tests/test_browser.py`.

### Measures

- The fixture (`tests/test_links.py::broken_pdf`): a GoTo whose `/A /D` names object 999, a
  GoTo to page 1 under the caption of TABLE 5.1-1 (which is on page 2), a GoTo turned into the
  named destination `lost-section` under "M3.2E0", a healthy GoTo under the caption of TABLE
  5.1-2, a URI, and the bookmark "5.2 M 12.6 Summary message" re-pointed at object 999. The
  report: dead → page 2, wrong page → page 2, unresolved, ok, external; the bookmark dead →
  page 3; one unlinked reference (TABLE 5.1-1 in the sentence on page 2). The fixed file re-checked:
  three ok, one unresolved, one external; the bookmark lands on page 3; every page's text equal
  before and after; a skipped fix stays dead; `add=True` adds the one link and leaves the healthy
  ones alone.
- The three refusals name the password, the permissions and the signature.
- The whole suite: **210 passed**, browser tests included. The checker on the 3-page fixture runs in
  well under a second; on a real standard, the time is the extractor's (the same read the library
  does on add).
- Not measured yet: a real standard of the owner's with broken links — the counts by state and the
  time per hundred pages are to be recorded when one is run (roadmap).
