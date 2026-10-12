# ADR-028: Distribution as a portable release

**Status:** proposed 2026-10-11 (draft for agreement; nothing built). Roadmap step 19. Extends
ADR-016's definition of a release.

## Context

A release today is a tag of the repository (ADR-016). Installing one means cloning the source,
having Python 3.10+ on the machine, and letting `install-service.ps1` create a virtual
environment from `requirements.lock` over PyPI, download WinSW from GitHub, and let the first run
download the embedding model. Four network steps and a Python install, on a machine meant to run
the app offline, for every target machine. The raw code travels each time.

What a running installation actually needs: the app (`src/`, the prebuilt `src/server/static`,
`docs/help`, `VERSION`), a Python with the locked packages (after ADR-027 about 1.3 GB
uncompressed, PyTorch most of it), the embedding model (about 440 MB), WinSW, and optionally
Tesseract and git on the machine. Node.js is not needed at run time (the front end is built and
committed; `.d.ts` reading uses tree-sitter, ADR-024).

Ways considered:

- **PyInstaller / cx_Freeze** — one frozen folder. PyTorch, transformers, PyMuPDF and the
  tree-sitter grammars each need hand-kept hidden-import and data-file lists; a fresh exe is
  flagged by antivirus; the result is still a gigabyte and still needs WinSW. Not worth it.
- **Docker** — not for a Windows desktop service reading the user's folders under a service
  account.
- **A wheel of the app** — still needs a Python and PyPI on the target; a by-product at most.
- **A portable folder** — Python's official embeddable distribution plus the locked packages
  installed into it, the app, the model and the deploy scripts, zipped. Nothing to install, nothing
  to download, nothing to build on the target. This is what the constraints ask for.

## Decision

### The release artefact

`Searchables-<version>-win64.zip`, unzipping to one folder:

```
Searchables-1.5.0-win64/
  python/                 Python 3.11 embeddable (python.org, x64) with Lib/site-packages holding
                          every package of requirements.lock as Windows wheels (CPU PyTorch)
  src/  VERSION  docs/help/   the app, static/ included; no tests, no web/ sources
  models/                 the pinned E5 model, so the first run is offline
  deploy/windows/         run.ps1, install-service.ps1, uninstall-service.ps1, README.md, WinSW-x64.exe
  LICENCES.md             the licences of every bundled Python package, the front end's (from
                          web/src/generated/licences.json), the model's and WinSW's
  README.md  RELEASE.md   RELEASE.md: version, commit, build date, what was bundled
```

- **Built from a tagged commit** by `deploy/build-release.py`, runnable on any platform: it
  downloads the embeddable Python zip and the Windows wheels (`pip download --platform
  win_amd64 --python-version 3.11 --only-binary=:all: -r requirements.lock`, CPU index for torch),
  unpacks the wheels into `python/Lib/site-packages` (pure unzip; no code of theirs is run),
  edits `python311._pth` to see `Lib/site-packages` and the app folder, copies the app and the
  model, writes `LICENCES.md` and `RELEASE.md`, and zips. Network is needed on the **build**
  machine only, and only for python.org, PyPI, GitHub (WinSW) and the model's host.
- **Pinned and reproducible:** the Python version, the WinSW version and the model revision are
  constants in the script beside the lock; the hashes of what was downloaded go into
  `RELEASE.md`. Building the same tag twice gives the same contents.
- **The scripts know the bundle:** `run.ps1` and `install-service.ps1` use `.\python\python.exe`
  when it exists and skip the venv, pip, WinSW download and model download; without it they
  behave as today, so a checkout still works for development. The service's environment sets
  `SEARCHABLES_MODEL_DIR` to the bundled `models/` and the data folder as now.
- **Upgrading:** unzip the new version beside the old one, run `install-service.ps1` from the new
  folder (it re-points the service), delete the old folder. The library (`data/`) lives outside
  the release folder by default (`deploy\windows\README.md` says where) and is untouched; the
  index migrations (ADR-004) run on start as they do now.
- **What stays external:** Tesseract (OCR; optional, its own installer), git (optional, for
  ADR-015/026), a browser. The README lists them as before.
- **macOS:** no bundle; the `deploy/macos` scripts stay as they are (PyTorch on Intel Macs is
  pinned and the audience is Windows). A later ADR if that changes.

### What a release is, from now on

ADR-016's "bump `VERSION`, commit, tag" gains a fourth step: build the zip from the tag and keep
it with the tag (a GitHub release asset, or the team's file share). `About` shows the version
and commit as now; `RELEASE.md` repeats them for a folder on disk.

### What is not done

- No installer (MSI/Inno Setup) — the scripts do the install; an installer can wrap the folder
  later without changing it.
- No code signing — a Python interpreter and scripts, not a fresh exe; nothing for SmartScreen to
  flag beyond the WinSW binary, which is the project's signed release.
- No automatic update check — the app is offline by design; the version is visible in About.
- No GPU PyTorch — the model runs on the CPU; the CPU wheel is a third the size.

## Measures

- The build script runs from this Mac and produces the zip from the current tag; the zip's size
  is recorded (expected 700–900 MB; the uncompressed folder under 2 GB).
- On a clean Windows VM with **no Python and no network**: unzip, `run.ps1` starts the server,
  the sign-in page opens, a PDF is added and searched (meaning search included, so the bundled
  model loads), a codebase is scanned and browsed; then `install-service.ps1` installs the
  service and it survives a reboot; `uninstall-service.ps1` removes it, keeping `data/`.
- Upgrade: a 1.5.0 folder installed beside a 1.4.0 one takes over the service and the library.
- `tests/test_release.py` checks the build script's manifest logic (what goes in, what is
  excluded: tests, web sources, `.git`, `data/`) and that `python311._pth` is written as
  intended, without downloading anything.

## Consequences

- `deploy/build-release.py`, `deploy/windows/*.ps1` with a bundle-aware branch, `tests/test_release.py`,
  a `RELEASE.md` template; `AGENTS.md`'s release line and `deploy/windows/README.md` gain the
  zip path ("download the release, unzip, run the script") as the first way to install, with the
  checkout way kept for developers.
- Depends on ADR-027 (Streamlit removal) going first: it takes about 280 MB out of the bundle.
- The environment variables table in the README gains `SEARCHABLES_PYTHON` for the scripts
  (the interpreter to use; default: the bundled one, else the `py` launcher).
