# ADR-015: Git status, diff and commit; rename symbol with preview

**Status:** accepted 2026-10-11 (agreed as part of the roadmap; the record for step 14, written
before building it).

## Context

Since ADR-011 the editor writes files; what changed and how to keep it belong in the same place.
ADR-001 allowed one program to be run for this: `git`, for status, diff and commit, never push.
Renaming a symbol is the one refactoring the index can do with its own knowledge: it knows every
linked reference and labels the uncertain ones, so a rename can be previewed reference by
reference and applied only to the ones confirmed.

## Decision

### Git (`src/code/git.py`)

- The `git` command (`SEARCHABLES_GIT`, else `git` on `PATH`), run only with the codebase root as
  its working directory, only for: `rev-parse --show-toplevel`, `status`, `diff`, `show HEAD:path`,
  `log`, `add` and `commit`. No push, fetch, pull, checkout, reset or anything touching a remote
  or the working tree beyond the commit; no hooks disabled, no config changed. When `git` or the
  repository is absent, the view says so and nothing else changes.
- Routes: `GET /api/codebases/{id}/git` (whether it's a repository, branch, status entries),
  `GET …/git/diff?path=` (unified diff of a file, working tree against HEAD),
  `GET …/git/log`, `POST …/git/commit` with the paths to stage and the message. Paths are checked
  as in ADR-011 (inside the folder, no escaping).
- A **Git** segment in the Code panel: branch, changed files with checkboxes, the diff of the
  chosen file, a message box and **Commit**. Files with unsaved changes in the editor are marked;
  committing them stages what's on disk, as git does.

### Rename symbol

- `POST /api/code/symbols/{id}/rename/preview` with the new name returns every place the name
  would change: the declaration, each linked reference (and those through a supertype), each
  template reference, and the by-name references that may be this symbol, each with file, line,
  column, the current line, its certainty, and whether it's selected by default (linked and
  supertype: yes; by name: no).
- `POST /api/code/symbols/{id}/rename` with the new name and the chosen edits checks that the text
  at each place is still the old name, applies the edits file by file through ADR-011's save path
  (hash-checked, atomic, form-preserving), re-links, and returns the files changed. A place whose
  text no longer matches is reported and skipped, not guessed.
- Overrides and overridden methods are renamed together (a method and what it implements), since
  renaming one without the others breaks the program; the preview says so.
- In the inspector: **Rename…** on the symbol head, the preview as a checklist grouped by
  certainty, **Apply**.

## Measures

- Git operations on a throwaway repository: status lists the edited file, diff shows the change,
  commit records it with the message; push is not offered (tests).
- Rename on the fixtures changes only confirmed references; by-name ones stay unless chosen; the
  index afterwards has the new name with the same usages (tests).

## As built

`src/code/git.py` (`info`, `diff`, `log`, `commit`; `GIT_TERMINAL_PROMPT=0`, stdin closed, a 30 s
timeout; no push function exists), `src/code/rename.py` (`preview_rename`, `apply_rename`: a file that
changed on disk since it was indexed has all its places skipped with that reason; overrides are found
through the hierarchy, and a declaration's name is looked for past leading annotations). Routes
`GET /api/codebases/{id}/git`, `…/git/diff?path=`, `…/git/log`, `POST …/git/commit`,
`POST /api/code/symbols/{id}/rename/preview`, `POST …/rename`. A **Git** segment and **Rename…** on the
symbol head. Tests: `tests/test_git_and_rename.py` (git on a throwaway repository), the API test.

## Consequences

- `src/code/git.py`, `src/code/rename.py`, routes, a Git segment and a rename dialog. ADR-001's
  "nothing is run" now reads: nothing of the codebase is run; `git` is the one program the app
  starts, for the operations listed, and the help says so.
