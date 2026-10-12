# ADR-028: Distribution as a portable release

**Status:** accepted 2026-10-11 with one change asked for at agreement: **macOS releases as well as
Windows** (the draft had none). Built the same day (roadmap step 19). Extends ADR-016's definition
of a release.

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
- **A portable folder** — a relocatable Python plus the locked packages installed into it, the
  app, the model and the deploy scripts, in one archive. Nothing to install, nothing to download,
  nothing to build on the target. This is what the constraints ask for.
- **Which Python to bundle:** python.org's *embeddable* distribution exists for Windows only. The
  `python-build-standalone` builds (the relocatable CPython that `uv` installs; PSF-licensed
  CPython, its build scripts MPL) exist for Windows x64, macOS arm64 and macOS x86_64 in one
  layout, so one build script serves every target. They are used for all three.

## Decision

### The release artefact

One archive per target — `Searchables-<version>-win64.zip`, `Searchables-<version>-macos-arm64.tar.gz`,
`Searchables-<version>-macos-x86_64.tar.gz` — each unpacking to one folder:

```
Searchables-1.5.0-<target>/
  python/                 CPython 3.11 (python-build-standalone, pinned release) with its
                          site-packages holding every package of requirements.lock as that
                          target's wheels (CPU PyTorch; on Intel Macs the pinned 2.2.2)
  src/  VERSION  docs/help/   the app, static/ included; no tests, no web/ sources
  models/                 the pinned E5 model, so the first run is offline
  deploy/windows/ or deploy/macos/   the scripts for that platform (WinSW-x64.exe bundled on Windows)
  LICENCES.md             the licences of every bundled Python package, the front end's (from
                          web/src/generated/licences.json), the model's, WinSW's and the Python build's
  README.md  RELEASE.md   RELEASE.md: version, commit, build date, target, what was bundled and its hashes
```

- **Built from a tagged commit** by `deploy/build-release.py --target win64|macos-arm64|macos-x86_64|all`,
  runnable on any platform: it downloads the pinned Python build, installs the locked wheels for the
  target with pip's cross-platform install (`pip install --target … --platform <tag>
  --python-version 3.11 --only-binary=:all: --require-hashes`; nothing of theirs is run), copies
  the app and the model (downloaded once with the app's own pinned call), writes `LICENCES.md`
  and `RELEASE.md`, and packs. PyPI's Windows and macOS PyTorch wheels are CPU builds, so no extra
  index is needed. Network is needed on the **build** machine only: GitHub (the Python build,
  WinSW), PyPI, and the model's host.
- **Pinned and reproducible:** the Python version, the WinSW version and the model revision are
  constants in the script beside the lock; the hashes of what was downloaded go into
  `RELEASE.md`. Building the same tag twice gives the same contents.
- **The scripts know the bundle:** `run.ps1`/`install-service.ps1` use `.\python\python.exe`, and
  `run.sh`/`install-service.sh` use `./python/bin/python3`, when they exist, and skip the venv,
  pip, WinSW download and model download; without them they behave as today, so a checkout still
  works for development. The service's environment points `SEARCHABLES_MODEL_DIR` at the bundled
  `models/`; the data folder stays where it is now.
- **Upgrading:** unzip the new version beside the old one, run `install-service.ps1` from the new
  folder (it re-points the service), delete the old folder. The library (`data/`) lives outside
  the release folder by default (`deploy\windows\README.md` says where) and is untouched; the
  index migrations (ADR-004) run on start as they do now.
- **What stays external:** Tesseract (OCR; optional, its own installer), git (optional, for
  ADR-015/026), a browser. The README lists them as before.
- **macOS:** two archives, Apple silicon and Intel, as `.tar.gz` so the interpreter keeps its
  execute bits. The bundled Python and its libraries are **not signed or notarized**; a download
  through a browser carries the quarantine attribute and Gatekeeper would refuse them, so
  `run.sh` and `install-service.sh` clear it on the bundle's own folder (`xattr -dr
  com.apple.quarantine`) on first run and say so. That is the known cost of an unsigned bundle; a
  Developer ID signature is a later decision.

### What a release is, from now on

ADR-016's "bump `VERSION`, commit, tag" gains a fourth step: build the zip from the tag and keep
it with the tag (a GitHub release asset, or the team's file share). `About` shows the version
and commit as now; `RELEASE.md` repeats them for a folder on disk.

### What is not done

- No installer (MSI/Inno Setup) — the scripts do the install; an installer can wrap the folder
  later without changing it.
- No code signing — on Windows a Python interpreter and scripts, not a fresh exe, with WinSW
  being that project's own release; on macOS the quarantine step above stands in for it.
- No automatic update check — the app is offline by design; the version is visible in About.
- No GPU PyTorch — the model runs on the CPU; the CPU wheel is a third the size.

## Measures

- The build script runs from this Mac and produces all three archives from the current commit;
  each archive's size is recorded (expected 700–900 MB; the unpacked folder under 2 GB).
- On this Mac (Intel or Apple silicon, whichever it is): unpack its own archive into a folder
  with no `.venv`, with the network switched off, `run.sh` starts the server, a PDF is added and
  searched with meaning, a codebase is scanned.
- On a clean Windows VM with **no Python and no network**: unzip, `run.ps1` starts the server,
  the sign-in page opens, a PDF is added and searched (meaning search included, so the bundled
  model loads), a codebase is scanned and browsed; then `install-service.ps1` installs the
  service and it survives a reboot; `uninstall-service.ps1` removes it, keeping `data/`.
- Upgrade: a 1.5.0 folder installed beside a 1.4.0 one takes over the service and the library.
- `tests/test_release.py` checks the build script's manifest logic (what goes in, what is
  excluded: tests, web sources, `.git`, `data/`) and that `python311._pth` is written as
  intended, without downloading anything.

## Consequences

- `deploy/build-release.py`, `deploy/windows/*.ps1` and `deploy/macos/*.sh` with a bundle-aware branch, `tests/test_release.py`,
  a `RELEASE.md` template; `AGENTS.md`'s release line and `deploy/windows/README.md` gain the
  zip path ("download the release, unzip, run the script") as the first way to install, with the
  checkout way kept for developers.
- Depends on ADR-027 (Streamlit removal) going first: it takes about 280 MB out of the bundle.
- The environment variables table in the README gains `SEARCHABLES_PYTHON` for the scripts
  (the interpreter to use; default: the bundled one, else the `py` launcher).

## As built

- `deploy/build-release.py --target win64|macos-arm64|macos-x86_64|all [--out dist] [--skip-model]`:
  fetches the pinned `python-build-standalone` build (3.11.17+20261009, `install_only_stripped`)
  and, for win64, WinSW v2.12.0, both cached under `dist/cache`; installs `requirements.lock` for
  the target with `pip install --target --platform <tag> --python-version 3.11 --only-binary=:all:
  --require-hashes` (no code of the wheels runs; the build machine's console scripts are removed);
  copies the app (`src/` without caches, `docs/help`, `VERSION`, README, the lock, the platform's
  `deploy/` folder) and the pinned model snapshot as plain files (the cache's symlinks resolved,
  blobs not duplicated); writes `LICENCES.md` (every dist-info's licence field and licence text, the
  front end's `licences.json`, the Python build's, the model's, WinSW's) and `RELEASE.md`; packs a
  zip (Windows) or tar.gz (macOS, execute bits kept).
- The scripts: `run.ps1`/`install-service.ps1` use `python\python.exe`, `run.sh`/`install-service.sh`
  use `python/bin/python3`, when present; they skip venv, pip, the model and the WinSW download, set
  `SEARCHABLES_MODEL_DIR` to the bundled `models/` (also into the service's environment), and on
  macOS clear the quarantine attribute on the release folder when the interpreter carries it.
- `tests/test_release.py` (no network): what `app_files` carries and excludes per target, the
  targets' pins, the licence reader, the release notes, and that the scripts know a bundle.
- `dist/` is git-ignored; `RELEASE.md` records the commit (an untagged build says which).

### Measures

- Built from this Mac in one run: **win64 621 MB** (unpacked 2.0 GB, 75 packages), **macos-arm64
  449 MB** (1.1 GB, 47 packages), **macos-x86_64 548 MB** (1.4 GB, 47 packages); the package counts
  differ because the lock's CUDA and Linux-only entries don't apply. Under the 700–900 MB expected,
  thanks to ADR-027 and the stripped Python build.
- The Intel macOS archive, unpacked into a fresh folder on this (Intel) Mac with `HF_HUB_OFFLINE=1`
  and `TRANSFORMERS_OFFLINE=1`: its own Python 3.11.17 starts, `src.server --check` passes, the
  bundled model embeds a sentence in 5 s on first load, `run.sh` starts the server in 2 s; and with
  pytest added beside the bundle, **52 server and library tests pass under the bundle's runtime**
  (a PDF added and searched with meaning, a codebase scanned and browsed, the API).
- Not measured here: the Windows archive on a clean Windows VM, and the service install on
  either platform — that is the user's part of the measure and stays open in the roadmap.
