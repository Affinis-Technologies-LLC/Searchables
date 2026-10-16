# Links

Check a PDF's internal links and bookmarks, and download it fixed. The file is read for the check and
held only for this session; it is **not added to the library**, and nothing is sent anywhere.

## What is checked

Every link annotation and every bookmark, against where the document itself puts each clause, table,
figure and annex (the same reading the Search view's inspector uses for "see TABLE 5.1-2"):

- **Dead** — the destination no longer exists (a page object dropped by a merge, a named destination
  nobody defines). The text under the link is read; when it names a table, figure, clause or annex the
  document has, the link is re-pointed there.
- **Wrong page** — the destination exists, but the text under the link names something the document
  puts on another page. Re-pointed there.
- **Unresolved** — dead, but the text under the link is not a reference the document can place. Listed
  for you; left as it is.
- **OK** — the destination exists and agrees with the text.
- **External** — a web address. Not checked: the app has no network.

Bookmarks are checked against the document's headings the same way: a bookmark whose destination is
gone or that points at a page other than its heading's is re-pointed; one matched by clause number
whose title differs is retitled as the heading reads; one whose title names no heading the document
has is left as it is and marked **unchecked**. **Headings without a bookmark** are listed, and a tick
**rebuilds the bookmarks from the headings** — every clause, levels from the numbers — replacing the
existing outline (off by default). The Library's Manage report has a **Bookmarks** row saying how the
stored PDF's outline agrees with the clauses found.

**References without a link** — text such as "see 4.2.3" with no link over it — are counted, and a
tick adds links for them (off by default).

## What is refused

A PDF that needs a password, one whose permissions forbid changing annotations, and a signed PDF (any
change would break the signature). Nothing is rewritten silently.

## The fixed file

Untick any fix you don't want, then **Download fixed PDF**. Only link annotations and the bookmarks
change; every page's text stays as it was (the file is re-saved, so it is not byte-identical). **Show**
opens the page with the link outlined; **Target** shows where it would point. **CSV** saves the report.
