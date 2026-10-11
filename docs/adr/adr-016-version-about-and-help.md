# ADR-016: A version, an About, and Help inside the app

**Status:** accepted 2026-10-11; built the same day (roadmap step 5).

## Context

The app has no version anywhere a user can see: `web/package.json` says `1.0.0` and means nothing,
the server reports none, and a bug report can't say which build it's about. There's no help inside
the app either; what the views do is in `README.md`, which the people using a deployed copy (ADR-007,
a Windows service) don't have in front of them. Everything must work offline (ADR-002), so help
can't be a link to a website.

## Decision

### Version

- **One source:** a `VERSION` file at the repository root holding a version like `1.4.0`
  (semantic: a change people must adapt to raises the first number; a new step of the roadmap the
  second; fixes the third). The release is a human act: bump the file, commit, tag `v1.4.0`.
- The server reads it at start (`src/version.py`) and adds, when `.git/HEAD` can be read, the short
  commit it was started from and whether the working tree is a checkout (the file is read; `git` is
  not run). `GET /api/session` and `/api/state` carry `version` and `commit`.
- The front end's build stamps its own version and build time (`import.meta.env`) so a stale
  `static/` next to a newer server is visible: About shows both and says when they differ.
- `python -m src.server --check` and the run scripts print the version.

### About

- The status bar's Account menu gains **About**: name, version and commit, the front end's build,
  where the library is (`SEARCHABLES_DATA_DIR`), the meaning-search model and whether it's present,
  Python and platform, counts (documents, codebases, pins), and the licences of what's bundled (the
  front-end dependencies and the Python ones, as a list read from a file written at build time).
- A **Copy** button puts the technical lines on the clipboard, for bug reports.

### Help

- A **Help** activity (the last in the activity bar, with `F1` as its shortcut): a table of
  contents on the left, the text in the main pane, searchable by words.
- The text lives in `docs/help/*.md`, one file per view, written for users (what the view shows,
  what each control does, the keyboard shortcuts, what the certainty labels mean, what the app
  never does: no AI, nothing leaves the machine, nothing is run). It's bundled into the front end at
  build time, so it's offline and matches the build.
- Rendering uses a small Markdown reader of our own (headings, paragraphs, lists, code, bold,
  links to other help pages and to views of the app) — no new dependency. Help pages can link into
  the app ("open the Catalogue") the way a view can be opened from the address.
- Every panel gets a **?** that opens its help page. The README keeps the installation and
  configuration parts and points to Help for the rest, so the two don't drift.

## As built

- `VERSION` (1.4.0: the three roadmap steps since the browser interface, and this one),
  `src/version.py` (`describe()`: version, short commit from `.git/HEAD` or `packed-refs`, whether
  it's a checkout), carried by `/api/session`, `/api/state` and `GET /api/about`; `--check` and the
  start-up line print it. The front end is stamped by `vite.config.ts` (`__APP_VERSION__`,
  `__BUILD_TIME__`); About says when server and interface differ.
- About: Account → **About**, a dialog with the technical lines and **Copy**; licences of the
  front-end dependencies from `web/src/generated/licences.json` (written by `npm run assets`,
  committed) and of the Python packages from their installed metadata at request time.
- Help: `docs/help/*.md` (one per activity plus `help.md`), bundled with `import.meta.glob`;
  the reader is `web/src/help/markdown.ts` (headings, paragraphs, lists, code, emphasis, inline
  code, key names, links); a Help activity with search, pages opened as tabs, `F1` opens the page of
  the view you're in, a **?** on every side panel. Links: `page.md`, `app:view`, `#heading`.
- Tests: `tests/test_help_and_version.py`, the API test, the browser flow,
  `web/src/help/markdown.test.ts` (renders every page).

## Options considered

- **Version from git tags only.** Not available on a deployed copy without git. The file is the
  source; the tag mirrors it.
- **Help as the README rendered.** The README mixes setup, architecture and use; users would wade
  through it. One file per view, written for them.
- **A Markdown library.** Adds a dependency and an audit surface for a dozen constructs; written
  in-house, tested on the help files themselves.

## Measures

- About shows a version that matches `VERSION`, the commit, and the front end's build; a test
  compares them with the files.
- Every activity has a help page; a test lists the activities and fails on a missing page or a
  broken link between pages.
- The help renderer's test renders every file in `docs/help/` and compares headings and links.
- Help search finds a view by a word from its page.

## Consequences

- A `VERSION` file, `src/version.py`, `docs/help/`, a `Help` activity, a build step that writes
  the dependency licences.
- Releases become explicit: a bump, a commit, a tag. `AGENTS.md` says so.
- Help pages must be updated with the view they describe; the test on activities keeps the set
  complete, not the content current, so a review step is needed when a view changes.
