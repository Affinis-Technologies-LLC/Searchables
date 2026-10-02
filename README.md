# Searchables

A research tool for standards and other technical PDFs, running entirely on your own machine. Add
documents to a library, then search them by words, by meaning and by identifier. Read the results on
the actual page with every hit highlighted, and follow how passages connect: references, shared
identifiers, defined terms, and passages on the same topic, with a note of how they differ.

It also browses **source code**: point it at a folder of Java, JavaScript or TypeScript and trace where
anything is declared and used, what calls what, which libraries and APIs the code depends on, and which
front-end calls reach which back-end routes (see [Source code](#source-code)).

It's designed for documents such as ISO/IEC standards and military standards (e.g. MIL-STD style
formatting), but works on any text-based or scanned PDF. Nothing is hard-coded to one document type:
clause structure, tables, figures and identifier patterns are discovered from each document.

## The interface

The app opens in your browser as a workbench, laid out like an IDE:

- **Views** down the left edge: Search, Contents (the open document's clauses), Glossary, Compare, Pins
  (collections), Code and Library. Each keeps its state while you use another.
- **Tabs** in the middle: every document and source file you open, each staying where you left it.
  Documents are shown as the real PDF page: search hits are highlighted, text can be selected, and
  clicking a passage explores it. **Alt+←** and **Alt+→** step back and forward through where you've been.
- **The inspector** on the right: for a document, what the passage connects to (Related), and the
  page's text, tables, references and defined terms; for code, the symbol under the cursor.
- **The status bar**: indexing progress, the collection pins go to, and your account.

The panels can be resized by dragging the dividers, and the layout follows your system's light or dark
setting. The address bar keeps the document, page and search in view, so a place can be bookmarked.

## Features

- **Library:** add PDFs once; they're indexed in the background while you keep working. A document is
  searchable by words as soon as its pages are read, and by meaning once its passages are read too.
  Indexing survives a restart: uploads still waiting are picked up again, and a document part-way
  through carries on from where it stopped. Duplicate files are detected; documents can be renamed,
  re-indexed or deleted.
- **Search by words and meaning:** one search box. Plain words and questions also match passages that
  say the same thing in other words; those are marked **meaning**. When few passages contain every
  word (a question rarely matches word for word), passages containing some of the words are listed
  after them. Exact syntax is available too: `"exact phrase"`, `OR`, `-exclude`, `prefix*`.
- **Long tables are found by their rows:** a table too long to be read whole is also read in runs of
  rows (each with the caption and header), so a row deep in a message or field table can be found by
  meaning, and the result shows the rows that matched.
- **Identifier search:** switch on **Identifier** to look up a message label, field number,
  requirement ID or part number exactly, with results grouped by role (headings and captions, table
  rows, rules, mentions) and related identifiers to follow.
- **Page viewer:** the real PDF page with hits highlighted and the passage outlined; page text, tables
  (as data, exportable to CSV), figures, cross-references and defined terms for each page.
- **Related:** from any passage, see what it references, what refers to it, passages sharing its
  identifiers or defined terms, and passages on the **same topic** in any document, assessed for how
  they differ: *different value* (e.g. 12 months → 6 months), *stronger/weaker requirement*
  (shall → should), *possible conflict* (shall vs shall not), *different identifiers*, *same content*.
- **Requirement filter:** show only requirements (shall), recommendations (should), permissions (may)
  or notes and examples. List items take the provision of their lead-in ("The terminal shall: a. … b. …").
- **Collections:** pin passages, tables and figures with notes; export a collection to Word or Markdown
  with citations.
- **Edition comparison:** clause-by-clause differences between two editions, including renumbered
  clauses and changed requirements.
- **Glossary:** terms and definitions from each document's "Terms and definitions" clause.
- **Source code:** the **Code** view browses Java, JavaScript and TypeScript codebases: symbol and text search,
  usages, caller and callee trees, type hierarchy, declared and used libraries, package dependencies,
  and HTTP routes matched to the calls that reach them.
- **Scanned pages** are read with OCR (Tesseract) when it's installed.
- **Sign-in:** a password protects the app, and the library folder is readable by your account only, so
  other accounts on the same machine can reach neither the app nor the stored PDFs. Reloading the page
  keeps you signed in; closing the browser, an hour without use, or restarting the app signs you out.

## Requirements

- **macOS or Windows 10/11** (Linux works too, without the provided service scripts).
- **Python 3.10 or newer.** On macOS, the built-in `python3` (3.9) is too old: install one with
  [Homebrew](https://brew.sh) or from [python.org](https://www.python.org/downloads/).
- **About 2 GB of disk space** for the Python packages (PyTorch) and the meaning-search model.
- **Tesseract** (optional, for scanned pages): `brew install tesseract` on macOS, or the
  [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) on Windows.
- **An internet connection once**, to install packages and download the model. After that the app
  runs fully offline.

## Getting started

**macOS**

```bash
git clone <this repository> ~/GitHub/Searchables
cd ~/GitHub/Searchables
deploy/macos/run.sh          # Opens on http://127.0.0.1:8501
```

**Windows** (PowerShell)

```powershell
cd C:\Apps\Searchables\deploy\windows
Set-ExecutionPolicy -Scope Process Bypass
.\run.ps1                    # Opens on http://127.0.0.1:8501
```

The first run creates a Python environment, installs the packages and downloads the model, which
takes several minutes. Later runs start straight away. Packages are installed from `requirements.lock`,
which pins every package (and its dependencies) to an exact version and file hash: pip refuses
anything else.

To run it as a background service that starts with the machine, see
[deploy/macos/README.md](deploy/macos/README.md) or [deploy/windows/README.md](deploy/windows/README.md).

**First use:** you'll be asked to create a password, then add PDFs in the **Library** tab.

## Meaning search: the model

Meaning search uses **Microsoft's E5 embedding model** (`intfloat/e5-base-v2`, MIT licence), run
locally with PyTorch and `sentence-transformers`:

- **It isn't a chatbot or LLM.** It can't write or answer anything; it turns each passage into a list
  of numbers representing its meaning, so passages about the same thing can be found and compared.
  Every result is a real passage from your documents.
- **It runs only on your machine.** It's downloaded once, pinned to an exact published version, into
  the `models/` folder; nothing is sent anywhere.
- **Exact items still rely on exact matching.** The model understands general technical English, not
  specialised codes, so identifiers, field numbers and values are handled by the keyword and
  identifier engines, which run alongside it.
- **The findings are rule-based.** In *Same topic*, the model only decides that two passages are about
  the same thing. How they differ (values, shall/should/may, negation, identifiers) is determined by
  fixed rules, so every finding can be explained.
- **Indexing is slower with it.** An older Intel Mac reads about 10 passages a second: a few minutes
  for a typical 100–300 page standard, and hours for a very large one (thousands of pages), once. It
  runs in the background, the document is searchable by words meanwhile, searches take priority over
  it, and it resumes after a restart.

The model is a setting in `src/config.py` (`EMBEDDING_MODEL`, `EMBEDDING_REVISION`). After changing it,
use **Add meaning search** in the Library view to re-process the documents.

## Source code

The **Code** view reads a codebase the way an IDE does, for reading and tracing rather than editing.
Source opens in an editor (the one inside VS Code, read-only): **F12** or **Ctrl/Cmd+click** on a name
goes to its declaration, hovering shows what it refers to, and the inspector on the right follows the
cursor with the symbol's usages, callers and callees, and hierarchy.

Add the top folder of the source (a path on the machine the app runs on); it's scanned in the
background, where it is. Nothing in the folder is changed. **Rescan** reads only new and changed files.

| View | What it shows |
|---|---|
| **Search** | Symbols (classes, interfaces, methods, functions, fields) by name, or any text in the source: a string, a URL, part of an identifier |
| **Symbol** | For the symbol being explored: where it's used, who calls it and what it calls (as trees, several levels deep), what it extends, implements or overrides, and its members. Everything you follow joins a trail you can step back along; **Pin** saves its source to a collection |
| **Dependencies** | Libraries declared in `pom.xml`, `build.gradle` and `package.json` (for npm, whether each is ever imported); outside packages actually imported, the APIs of each in use and where; and which package (or folder) depends on which |
| **APIs** | HTTP routes the code serves (Spring, JAX-RS, Express) with the calls that reach them (`fetch`, axios, `$.ajax`, HTTP clients), matched by method and path; routes nothing calls, and calls to routes served elsewhere |
| **Files** | Any file by path; files the parser couldn't fully read |

The viewer shows the source with the line in question highlighted, the file's outline, what the lines
on screen refer to (to follow, as you would by clicking through in an IDE), and the file's imports and
importers.

**How it works, and how far to trust it.** Files are parsed with [tree-sitter](https://tree-sitter.github.io/)
(a parser, not a language model; it runs locally and copes with files that have syntax errors). Each
reference is then linked to its declaration the way a compiler would where that can be told from the
source alone: through imports (including `tsconfig.json` path aliases and `require`), declared types,
inheritance and scope. Every link is labelled:

- **Linked:** followed for certain.
- **Through a supertype:** a call made through an interface or superclass method that this one implements.
- **By name only:** the name and number of arguments agree, but what it's called on couldn't be told
  without compiling the code (a chained call, a lambda parameter, most of dynamic JavaScript). Check
  these before relying on them.

It doesn't compile the code, so it won't match an IDE for calls through inferred types, reflection or
dependency injection. JavaScript and TypeScript are read file by file: `.js`, `.jsx`, `.mjs`, `.cjs`,
`.ts`, `.tsx`. Build output and downloaded dependencies (`node_modules`, `target`, `build`, `dist`, `out`,
folders starting with a dot), minified bundles, `.d.ts` files and files over 1 MB are skipped; the list
is `CODE_SKIP_FOLDERS` in `src/config.py`.

A scan reads roughly 70 files a second on an older Intel Mac (a 3,000-file codebase in under a minute).
The index keeps a copy of each file's text, for searching and showing it, in the library folder.

## Your data

Everything stays on your machine, in two git-ignored folders:

| Folder | Contains |
|---|---|
| `data/` | The library: copies of your PDFs, the search index, the code index (including the text of indexed source files), collections, search history, logs and the password hash (`auth.json`) |
| `models/` | The downloaded meaning-search model |

Keep licensed or distribution-restricted documents out of the repository: they belong in `data/`,
which git ignores. Don't paste their content into online tools.

The library folder is private to your account (on Windows, the service's install script limits it to
administrators and the service account). The files in it aren't encrypted, so keep the disk encrypted
(FileVault, BitLocker).

**Forgotten password:** delete `data/auth.json` and restart the app to set a new one. Your documents
and collections are kept.

## Configuration

Most behaviour is set in `src/config.py`: identifier discovery thresholds, how many related passages
are shown, meaning-search thresholds, OCR language, sign-in lockout and idle time-out, and for source
code the folders skipped, the largest file read, and how deep call trees go.

| Environment variable | Default | Purpose |
|---|---|---|
| `SEARCHABLES_DATA_DIR` | `data/` in the project | Where the library is kept |
| `SEARCHABLES_MODEL_DIR` | `models/` in the project | Where the meaning-search model is kept |

## Checking search quality

The thresholds in `src/config.py` (how similar a passage must be to count as a meaning match, when
partial matches are listed, and so on) should be set on evidence from your own documents:

```bash
cp eval_queries.example.json data/eval_queries.json   # Then describe your own searches in it
.venv/bin/python -m src.evaluate                      # or: python -m src.evaluate my_queries.json --k 10
```

Each entry is a search and the passages a good search must find (by document, clause, page or words
they contain). The report gives the rank of the first expected passage for words alone, meaning alone
and both combined, and for passages meaning search missed, how similar the model found them. Keep the
queries file in `data/`: it describes your documents.

## Developing the interface

The server (`src/server`, Python) answers a JSON API and serves the front end. The front end (`web/`,
TypeScript and React, with the Monaco editor and PDF.js) is built into `src/server/static`, which is
committed, so running the app needs no Node.js. To change the front end you need Node.js 20 or newer:

```bash
cd web
npm ci                 # Installs the exact versions in package-lock.json
npm run dev            # A reloading copy on http://localhost:5173, using the server on port 8501
npm run build          # Type-checks, then rebuilds src/server/static
```

The earlier Streamlit interface (`app.py`, `src/ui/`) is still in the repository but switched off:
started the old way, it only says how to start the new one. It runs with `SEARCHABLES_STREAMLIT=1`
set, until it's removed.

## Tests

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The tests build their own small PDFs and use a stand-in for the language model, so they need neither
your documents nor the downloaded model, and never touch your library. One of them drives the whole
app in Google Chrome (through Playwright); it's skipped when either isn't installed.

## Updating packages

`requirements.txt` lists what the app needs; `requirements.lock` is generated from it with
[uv](https://docs.astral.sh/uv/) and covers every supported platform:

```bash
uv pip compile requirements.txt --universal --generate-hashes --python-version 3.10 -o requirements.lock
```

## Project layout

See [APP_LAYOUT.md](APP_LAYOUT.md) for what each module does.

## Notes

- **Intel Macs:** PyTorch stopped supporting them after version 2.2.2, so `requirements.txt` installs
  that version (with numpy 1.x) there, and current versions elsewhere.
- **Appendices numbered in tens:** older MIL-STD appendices number their sections 10, 20, 30… in every
  appendix, so a reference such as "see 10.1" can't say which appendix it means; it opens the first.
- **Licence:** this project builds on [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed
  under the AGPL 3.0 or a commercial licence from Artifex. Choose this project's licence accordingly.
