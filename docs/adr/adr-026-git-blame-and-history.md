# ADR-026: Git blame and history, read-only (amendment to ADR-015)

**Status:** accepted 2026-10-11; built the same day (roadmap step 17). Extends the list of `git`
operations in ADR-015; everything else there stands.

## Context

The tool's question is often not "what does this code do" but "when did it come to be this way,
and with what". A clause of a standard is traced to code (ADR-014); the next question is which
change put it there and whether it moved since. ADR-015 allowed `git` for status, diff, log and
commit, and no more. Blame and per-file history are the two reading operations that answer the
"when" question, and they need nothing but the repository that is already on disk. They are
read-only, so the one property ADR-015 protects (never push, never touch a remote, never change
the working tree beyond a commit) is untouched.

What is deliberately not in scope, as before: branches, stash, merge, checkout, reset, push. The
app is one shared working copy behind a service account; a branch switch by one person changes
what everyone else is editing.

## Decision

### Operations added to ADR-015's list

All run as before: the `git` command, the codebase root as working directory, paths checked
inside the root, `GIT_TERMINAL_PROMPT=0`, a 30 s timeout, stdin closed, nothing else.

- `git blame --porcelain [-L start,end] -- <path>` — per line: commit, author, author time,
  summary; lines not yet committed are reported as **uncommitted** (git's all-zero commit).
  Blame is of the file **as on disk**, so an unsaved editor buffer is not what is blamed; the
  view says so when the tab has unsaved changes.
- `git log --follow --format=… -- <path>` — the commits that changed a file, renames followed.
- `git log -L <start>,<end>:<path> --format=…` — the commits that changed a **range** of a file,
  used for a symbol's declaration (its first to last line): the history of a method or class
  rather than of its file. The diff bodies git prints with `-L` are discarded; only commit
  headers are kept. Limited to the newest 30 commits.
- `git show --format=… --stat <commit>` and `git show --format= <commit> -- <path>` — one
  commit: its message, author, date, the files it changed, and its diff for one file.
  A commit id is accepted only as 4–40 hex digits; branch names, `HEAD~1` and the like are refused
  (they aren't needed, and keeping the grammar small keeps the review of what runs small).

No new write operation. `src/code/git.py` keeps the one `_run`, and its docstring lists the
operations; a test asserts the module contains no `push`, `fetch`, `pull`, `checkout`, `reset`,
`rebase`, `merge`, `stash` or `branch` invocation.

### Where it shows

- **Editor — Blame.** A toggle on the code tab (`Blame`) adds a column at the left of each line
  with the author's initials and the date, the full commit summary on hover; a click opens that
  commit in the Git segment. Lines **uncommitted** are marked as such. Blame is fetched once per
  file version and dropped when the file is saved or the index changes.
- **Inspector — File view: History.** The file's commits (`--follow`), newest first: date,
  author, summary; choosing one shows its diff for this file.
- **Inspector — symbol head: History.** For a method, class, function or field: the commits that
  changed its lines (`-L`), the same way. It answers "when did this change last, and what else
  changed with it".
- **Git segment.** A log entry opens the commit: message, files changed, and the diff of a chosen
  file.
- **Catalogue — "In the code" (ADR-014).** Each mention gains the date of the commit that last
  changed its line (from blame of that line), so a standard's identifier can be read against when
  its code last moved. This is the one place blame reaches the standards side; it stays a mention
  with a date, not a claim.

### What is not done

- No blame of an unsaved buffer (git has no such file); no blame across a rename beyond what git
  does itself (`--follow` for history only; blame follows copies within the file as git does by
  default).
- No history of a Catalogue identifier as such (only of the code lines that mention it).
- No branch, tag or remote information beyond the current branch name ADR-015 already shows.
- No caching across restarts: blame and history are read from git when asked and kept per
  process only.

## Measures

- Tests first, on a throwaway repository (the pattern of `tests/test_git_and_rename.py`): blame
  attributes lines to the commits that wrote them and marks an edited, uncommitted line; a file's
  history follows a rename; a method's history lists the commit that changed the method and not
  the commit that changed another method in the same file; `show` of a commit for a path returns
  only that path's diff; a commit id that isn't hex is refused; the module makes no write call
  beyond `add` and `commit`.
- The API test covers the four routes; the browser test toggles Blame and sees a column.
- Time: blame of a 5,000-line file in under 2 s on the corpus's repository (git's own time); a
  symbol's `-L` history in under 5 s, else truncated with a note.

## Consequences

- `src/code/git.py` gains `blame`, `history`, `symbol_history`, `show`; routes `GET
  /api/codebases/{id}/git/blame?path=&start=&end=`, `…/git/history?path=`,
  `…/git/history?path=&start=&end=`, `…/git/show?commit=&path=`.
- `CodeView.tsx` gets the Blame column (Monaco line decorations with a margin), the inspector's
  File view a History list, the symbol head a History view, `GitView.tsx` a commit panel, the
  Catalogue's "In the code" a date per mention.
- ADR-015's operations list reads: status, diff, log, blame, show and commit. Help's Code page and
  About's "git is the one program it starts" line name the reading operations too.

## As built

- `src/code/git.py`: `blame` (porcelain, optional `-L`; the all-zero commit becomes `uncommitted`),
  `history` (`--follow` for a file, `-L start,end:path` for a symbol's lines, headers only, newest
  30), `show` (`--numstat` for the files, renamed paths read as their new name, and the diff for one
  path when asked). Commit ids: 4–40 hex digits, else refused. Off a repository, or without git,
  blame and history answer empty rather than failing, the way the Git segment says "not a
  repository". `test_git_module_only_reads_and_commits` asserts no `_run` line names push, fetch,
  pull, checkout, reset, rebase, merge, stash or branch.
- Routes: `GET /api/codebases/{id}/git/blame?path=&start=&end=`, `…/git/history?path=&start=&end=`,
  `…/git/show?commit=&path=`; `GET /api/catalogue/code` dates each mention's line (one blame per
  file, at most twenty files per answer).
- Interface (`web/src/code/history.tsx`): the **Blame** column beside the editor (initials and
  date, one label per run of a commit, uncommitted lines in italics, "on disk" while the tab has
  unsaved changes; a click opens the commit), the inspector's **History** view (the chosen symbol's
  lines or the whole file, one commit opened below with its files and this file's diff), the Git
  segment's recent commits opening the same panel with a file chooser, and the date on each
  Catalogue mention.
- One thing the ADR said that git doesn't do: `show <commit> -- <path>` for a rename commit shows
  the file as all additions, since rename detection needs both paths in the pathspec; the files
  list shows the new name, which is enough to see the move.

### Measures

- Tests: blame attributes committed lines and marks an edited one; a file's history follows a
  rename (`Order.java` → `Purchase.java`); a method's history lists the commit that touched it and
  not the one that reformatted another method in the same file; `show` returns only the path's
  diff; `HEAD~1`, `main` and `abc;rm` are refused; the API test covers the three routes on a
  throwaway repository and the empty answer off one; the browser test toggles Blame, sees a dated
  line and an uncommitted one, and finds the commit in History.
- Time, on this repository: blame of `src/code/store.py` (2,265 lines, 5 commits) 0.09 s; its file
  history 0.05 s; a 60-line range's history 0.02 s. The 3,000-file corpus has a single commit, so
  its numbers (0.02 s) say little; the bounds in the decision (2 s and 5 s) are git's own and were
  not approached.
