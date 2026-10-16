# Help

Searchables is a research tool for standards PDFs and source code. It runs on this machine, from a
folder of documents and codebases you give it, and answers with passages and code that exist.

## What it never does

- **No AI.** Nothing is generated or summarised. Search ranks real passages by the words they
  contain and by meaning (a local language model that only compares text; it writes nothing);
  code examples are statements copied from the codebase, with their file and line.
- **Nothing leaves the machine.** Documents, code, searches and notes stay in the app's data
  folder. The meaning model is downloaded once and used offline.
- **Nothing of the codebase is run.** The code views read source files; they never build, test,
  format or execute anything. The only files written are the ones you save in the editor. The
  one program the app starts is `git`, for status, diff, log, blame, show and commit only; it
  never pushes, pulls or changes the working tree.

## The views

Each view is a button in the bar on the left. `F1` opens this help; the **?** at the top of each
view opens its page.

- [Search](search.md): the documents, by words, by meaning, or by identifier
- [Contents](contents.md): the open document's clauses
- [Catalogue](catalogue.md): identifiers as entries, and what changed between editions
- [Glossary](glossary.md): defined terms and acronyms
- [Compare](compare.md): two editions side by side
- [Pins](collections.md): collections of passages, tables and code, with notes, exported to Word
- [Code](code.md): browse, edit and get examples from a codebase
- [Library](library.md): add documents and keep them indexed
- [Links](links.md): check a PDF's internal links and bookmarks and download it fixed

## Moving about

- `Alt`+`←` and `Alt`+`→` step back and forward through what you've looked at, as in a browser.
- Tabs across the top hold the open documents and files; a tab with **●** has unsaved changes.
- The bar at the bottom shows what's being indexed, the **Cite when copying** switch, the
  collection pins go to, and **Account**, where you'll find **About** with the version to quote in
  a bug report.
