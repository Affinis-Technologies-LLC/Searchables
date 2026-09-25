# Searchables

A research tool for standards and other technical PDFs, running entirely on your own machine. Add
documents to a library, then search them by words, by meaning and by identifier. Read the results on
the actual page with every hit highlighted, and follow how passages connect: references, shared
identifiers, defined terms, and passages on the same topic, with a note of how they differ.

It's designed for documents such as ISO/IEC standards and military standards (e.g. MIL-STD style
formatting), but works on any text-based or scanned PDF. Nothing is hard-coded to one document type:
clause structure, tables, figures and identifier patterns are discovered from each document.

## Features

- **Library:** add PDFs once; they're indexed in the background while you keep working. Duplicate
  files are detected; documents can be renamed, re-indexed or deleted.
- **Search by words and meaning:** one search box. Plain words and questions also match passages that
  say the same thing in other words; those are marked **meaning**. Exact syntax is available too:
  `"exact phrase"`, `OR`, `-exclude`, `prefix*`.
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
  or notes and examples.
- **Collections:** pin passages, tables and figures with notes; export a collection to Word or Markdown
  with citations.
- **Edition comparison:** clause-by-clause differences between two editions, including renumbered
  clauses and changed requirements.
- **Glossary:** terms and definitions from each document's "Terms and definitions" clause.
- **Scanned pages** are read with OCR (Tesseract) when it's installed.
- **Sign-in:** a password protects the app, including from other accounts on the same machine.

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
takes several minutes. Later runs start straight away.

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
- **Indexing is slower with it.** On an older Intel Mac, a typical 100–300 page standard takes 1–3
  minutes and a very large one (thousands of pages) about 25 minutes, once. It runs in the background.

The model is a setting in `src/config.py` (`EMBEDDING_MODEL`, `EMBEDDING_REVISION`). After changing it,
use **Add meaning search** in the Library tab to re-process the documents.

## Your data

Everything stays on your machine, in two git-ignored folders:

| Folder | Contains |
|---|---|
| `data/` | The library: copies of your PDFs, the search index, collections, search history, logs and the password hash (`auth.json`) |
| `models/` | The downloaded meaning-search model |

Keep licensed or distribution-restricted documents out of the repository: they belong in `data/`,
which git ignores. Don't paste their content into online tools.

**Forgotten password:** delete `data/auth.json` and restart the app to set a new one. Your documents
and collections are kept.

## Configuration

Most behaviour is set in `src/config.py`: identifier discovery thresholds, how many related passages
are shown, meaning-search thresholds, OCR language, sign-in lockout and idle time-out.

| Environment variable | Default | Purpose |
|---|---|---|
| `SEARCHABLES_DATA_DIR` | `data/` in the project | Where the library is kept |
| `SEARCHABLES_MODEL_DIR` | `models/` in the project | Where the meaning-search model is kept |

## Project layout

See [APP_LAYOUT.md](APP_LAYOUT.md) for what each module does.

## Notes

- **Intel Macs:** PyTorch stopped supporting them after version 2.2.2, so `requirements.txt` installs
  that version (with numpy 1.x) there, and current versions elsewhere.
- **Licence:** this project builds on [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed
  under the AGPL 3.0 or a commercial licence from Artifex. Choose this project's licence accordingly.
