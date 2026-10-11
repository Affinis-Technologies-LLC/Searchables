# ADR-011: The writable editor, file safety, and the index on save

**Status:** accepted 2026-10-11; built the same day (roadmap step 2). Measured on the 3,000-file corpus: a
save settles in 0.04–0.06 s once the linker's state is warm (about 1 s for the first save after the server
starts, which loads it). The browser test saves, provokes a conflict and compares the two versions.

## Context

The Code view shows source read-only in Monaco. Steps 3 and 4 (examples as you type, patterns) need
a developer to be writing code in the tool, and the index to describe what they have just written.
That means the server writes into the codebase folder for the first time, and the index must be
updated on every save quickly enough not to be noticed. Debugging, compilation, running builds or
tests, and a language server stay out of scope (ADR-001); git is step 6 (ADR-015).

Today a folder is read where it is and nothing is written into it (ADR-006). Re-linking one file
after a change takes about 0.9 s on a 3,000-file corpus because the linker loads every symbol
and import each time (ADR-010).

## Decision

### What the server may write

- **Only inside a registered codebase's folder**, resolved to a real path; a path that escapes the
  folder, or that goes through a symbolic link leading out of it, is refused. Folders skipped by
  scanning (`node_modules`, build output, dot-folders) can't be written either.
- **Only files of the kinds the index reads**: source files of the indexed languages, Angular
  templates, build files and `tsconfig`/`jsconfig`. Nothing else is created, changed or deleted.
- **Saves are atomic**: the new content is written to a temporary file beside the target and renamed
  over it, so a crash leaves either the old file or the new one.
- **A save carries the hash the editor opened the file with**; if the file on disk has since changed
  (another editor, a `git pull`), the save is refused with both versions available, and the editor
  shows the difference and lets the developer choose. The same hash check applies to renames,
  moves, deletes and multi-file replacements.
- **The file's form is kept**: its line endings (`\r\n` or `\n`), a leading byte-order mark, and its
  encoding (UTF-8, UTF-16 with BOM) are recorded when it's read and reproduced when it's written.
  The index keeps working on the normalised text as now.
- **No running of anything.** No build, test, format or shell command is started by the server.

### Editing

- **The editor is writable** for files of the indexed kinds. Changes live in the browser until saved
  (`Ctrl/Cmd+S`); a modified tab shows a mark; closing a modified tab asks. Unsaved text survives
  switching tabs and views, and is kept per file in the browser's storage so a reload doesn't lose it.
- **Files**: new file (in a chosen folder), rename, move, delete, with the same hash checks; the file
  tree updates without a rescan.
- **Project-wide find and replace**: find uses the text index as now; replace is one request listing
  every change with the file hashes, applied all-or-nothing, previewed first.
- **No formatting** (no formatter that needs no runtime has been chosen) and **no rename of symbols**
  (ADR-015, which needs the certainty labels shown per reference).

### The index on save

- A saved file is **re-parsed and re-linked in place**: its old symbols, references, imports,
  endpoints and components are replaced, and the references elsewhere to what it declares (and
  by-name references its new declarations may satisfy) are linked again, as ADR-010's partial pass
  does, including templates.
- The linker's working state (symbols, members, imports, bindings) is **kept in memory per codebase**
  and updated for the changed file instead of being rebuilt, so a save settles in well under a
  second on a codebase of thousands of files. A full rescan still rebuilds it.
- Ids of unchanged symbols don't change; the symbol under the cursor stays the same symbol.
- The response to a save returns the new outline and the file's new id, so the editor updates its
  model, decorations and inspector without a reload.

### Front end

- Monaco in writable mode, with the same navigation; the inspector follows the cursor as now, on
  the saved index (what's typed but unsaved is step 3's concern).
- **Front-end unit tests** begin with this step (Vitest, run by `npm test`), for the editor state
  (dirty, save, conflict) and the file operations; the browser test covers the whole flow.

## Options considered

- **Auto-save on every keystroke.** Simpler for the index, but it writes what the developer hasn't
  decided to keep and it defeats the hash check. Explicit save, with unsaved text kept in the browser.
- **Re-link the whole codebase on save.** Correct and simple, 20–40 s on 3,000 files. No.
- **A file watcher** re-indexing on outside changes. Useful but another moving part; deferred. Outside
  changes are caught at save time by the hash, and by the next rescan.
- **Allowing any file to be edited.** Would turn the tool into a general editor and widen what the
  server writes; limited to what the index understands.

## Measures

- A save of one file on the 3,000-file corpus, including re-parse and re-link, under 0.3 s on the
  server and under a second end to end in the browser.
- After a save, the index equals a full rescan's (a test compares every linked reference).
- A save with a stale hash is refused and nothing is written; a conflicting edit is shown.
- Line endings, byte-order mark and encoding are unchanged after a save (tests with CRLF, BOM, UTF-16).
- A directory listing with hashes of every file not edited is identical before and after a session
  of edits (nothing else is touched).
- Writes outside the folder, through symlinks, or to unindexed file kinds are refused (tests).

## Consequences

- The server needs write access to the codebase folder; on Windows as a service that's the service
  account's access, which the Windows README must say how to grant.
- The code index gains per-file form metadata (line endings, BOM, encoding) and a long-lived linker
  state per codebase; both additive (ADR-004).
- `web/` gains Vitest and its first unit tests, closing the gap named in ADR-008.
- Working copies now change through the tool; git integration (ADR-015) becomes the way to see and
  keep those changes, and should follow soon after.

## As built

- `CodeStore.save_file`, `create_file`, `rename_file`, `delete_file`, `replace_in_files` and
  `relink_files`; `Conflict` carries the current text and hash and becomes a 409. The file's form
  (encoding, byte-order mark, line endings) is a JSON column `code_files.form`. Symbols kept across a
  save (same kind, qualified name and parameter count) keep their ids.
- The linker (`_Linker`) is kept per codebase in `CodeStore._linkers`: `load()` once, `refresh(files)`
  per save, `run(only_files=…)` selecting the references to link again from what it knows (the files,
  their importers, the symbols replaced, the names newly declared). A partial index
  `code_refs_unlinked` makes "by-name references with these names" exact; a rescan drops the state.
- API: `PUT /api/code/files/{id}` (text + sha256), `POST /api/codebases/{id}/files`,
  `POST /api/code/files/{id}/rename`, `DELETE /api/code/files/{id}` (sha256 in the body),
  `GET`/`POST /api/codebases/{id}/replace`. Refused while that codebase is being scanned.
- Front end: `web/src/code/drafts.ts` (unsaved text, conflicts, browser storage; unit-tested with
  Vitest in `drafts.test.ts`), `editing.ts` (the calls), the editor's save action and conflict
  notice with a side-by-side comparison, unsaved marks on tabs with a save/discard question on
  closing, new/rename/delete in the Files view, Replace in the Text search. `npm run build` runs
  the unit tests.

## Open questions

- Should the editor's unsaved text be visible to the inspector before saving (parse the buffer, as
  step 3 will)? Not in this step: the inspector describes saved code, and the editor says so.
- Should saves be limited to one codebase at a time, or can tabs from several codebases be saved
  independently? Independently; each save names its codebase and file.
