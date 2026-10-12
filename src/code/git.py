"""
Git status, diff, log, blame, show and commit (ADR-015, ADR-026): the one program the app starts,
run only with a codebase's folder as its working directory and only for the operations here. No
push, fetch, pull, checkout or reset; nothing touching a remote; nothing changing the working tree
beyond the commit.
"""
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

TIMEOUT = 30


@dataclass
class Entry:
    path: str
    status: str                 # Two characters as git prints them: " M", "M ", "A ", "D ", "??", …
    old_path: str = ""          # Renames


@dataclass
class Info:
    repository: bool
    branch: str = ""
    entries: List[Entry] = field(default_factory=list)
    reason: str = ""            # Why there's nothing: no git, not a repository


@dataclass
class Commit:
    commit: str
    author: str
    date: str
    message: str


@dataclass
class CommitResult:
    committed: bool
    commit: str
    output: str


@dataclass
class BlameLine:
    line: int
    commit: str                 # Short id; "" for a line not yet committed
    author: str
    date: str                   # YYYY-MM-DD
    summary: str
    text: str
    uncommitted: bool = False


@dataclass
class ChangedFile:
    path: str
    added: int
    removed: int


@dataclass
class Shown:
    commit: str
    author: str
    date: str
    message: str                # Subject and body
    files: List[ChangedFile]
    diff: str                   # For the one path asked for, else ""


HISTORY_LIMIT = 30
_COMMIT_ID = re.compile(r"^[0-9a-f]{4,40}$")


def _git() -> Optional[str]:
    return os.environ.get("SEARCHABLES_GIT") or shutil.which("git")


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    exe = _git()
    if exe is None:
        raise ValueError("git isn't installed (or set SEARCHABLES_GIT to its path).")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run([exe, "-c", "core.quotepath=off", *args], cwd=str(root), capture_output=True, text=True,
                            timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    if check and result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"git {args[0]} failed.")
    return result


def _inside(root: Path, relative: str) -> str:
    relative = relative.replace("\\", "/").strip().strip("/")
    parts = relative.split("/")
    if not relative or any(p in ("", ".", "..") for p in parts) or ":" in relative:
        raise ValueError(f"“{relative}” isn't a path inside the codebase.")
    if not (root / relative).resolve().is_relative_to(root.resolve()):
        raise ValueError(f"“{relative}” leads outside the codebase folder.")
    return relative


def info(root: Path) -> Info:
    """Whether the folder is in a repository, the branch, and the changed files (paths relative to the folder)."""
    if _git() is None:
        return Info(False, reason="git isn't installed")
    top = _run(root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0:
        return Info(False, reason="not a git repository")
    branch = _run(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip() or "(no commits yet)"
    status = _run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".")
    entries = []
    items = status.stdout.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        if len(item) < 4:
            i += 1
            continue
        code, path = item[:2], item[3:]
        old = ""
        if code[0] in "RC":
            i += 1
            old = items[i] if i < len(items) else ""
        entries.append(Entry(path, code, old))
        i += 1
    return Info(True, branch, sorted(entries, key=lambda e: e.path))


def diff(root: Path, relative: str) -> str:
    """The unified diff of a file's working copy against HEAD; a new file shows as all additions."""
    relative = _inside(root, relative)
    tracked = _run(root, "ls-files", "--error-unmatch", "--", relative, check=False).returncode == 0
    if not tracked:
        text = (root / relative).read_text(errors="replace") if (root / relative).is_file() else ""
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return f"--- /dev/null\n+++ b/{relative}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{l}\n" for l in lines)
    return _run(root, "diff", "--no-color", "HEAD", "--", relative).stdout


def log(root: Path, limit: int = 20) -> List[Commit]:
    out = _run(root, "log", f"-n{limit}", "--format=%h%x1f%an%x1f%ad%x1f%s", "--date=short", check=False)
    commits = []
    for line in out.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(Commit(*parts))
    return commits


def commit(root: Path, paths: Sequence[str], message: str) -> CommitResult:
    """Stages the given paths (inside the folder) and commits them with the message. Never pushes."""
    message = message.strip()
    if not message:
        raise ValueError("A commit needs a message.")
    if not paths:
        raise ValueError("Choose the files to commit.")
    relative = [_inside(root, p) for p in paths]
    _run(root, "add", "-A", "--", *relative)
    result = _run(root, "commit", "--only", "-m", message, "--", *relative, check=False)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or "git commit failed.")
    head = _run(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return CommitResult(True, head, result.stdout.strip())


def _nothing_to_show(stderr: str) -> bool:
    """Not a repository, a file git doesn't know, or no commits yet: an empty answer, not an error."""
    return any(s in stderr for s in ("not a git repository", "no such path", "is outside repository", "does not have any commits",
                                      "has only", "bad revision", "unknown revision"))


def _commit_id(commit: str) -> str:
    commit = commit.strip().lower()
    if not _COMMIT_ID.match(commit):
        raise ValueError("A commit is named by its id (hex digits).")
    return commit


def blame(root: Path, relative: str, start: int = 0, end: int = 0) -> List[BlameLine]:
    """Who last changed each line of a file as it is on disk; lines not yet committed are marked."""
    relative = _inside(root, relative)
    args = ["blame", "--porcelain", "--date=short"]
    if start and end:
        args.append(f"-L{start},{end}")
    if _git() is None:
        return []   # Nothing to show, the way the Git segment says so
    out = _run(root, *args, "--", relative, check=False)
    if out.returncode != 0:
        if _nothing_to_show(out.stderr):
            return []
        raise ValueError(out.stderr.strip() or "git blame failed.")
    commits: dict = {}
    lines: List[BlameLine] = []
    current = None
    for raw in out.stdout.split("\n"):
        if current is None:
            parts = raw.split(" ")
            if len(parts) < 3 or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
                continue
            current = {"id": parts[0], "line": int(parts[2])}
            commits.setdefault(parts[0], {"author": "", "date": "", "summary": ""})
        elif raw.startswith("\t"):
            info = commits[current["id"]]
            short = current["id"][:7]
            uncommitted = current["id"] == "0" * 40
            lines.append(BlameLine(current["line"], "" if uncommitted else short, "" if uncommitted else info["author"],
                                   "" if uncommitted else info["date"], "" if uncommitted else info["summary"], raw[1:], uncommitted))
            current = None
        else:
            key, _, value = raw.partition(" ")
            if key == "author":
                commits[current["id"]]["author"] = value
            elif key == "author-time":
                from datetime import datetime, timezone
                commits[current["id"]]["date"] = datetime.fromtimestamp(int(value), timezone.utc).strftime("%Y-%m-%d")
            elif key == "summary":
                commits[current["id"]]["summary"] = value
    return lines


def history(root: Path, relative: str, start: int = 0, end: int = 0, limit: int = HISTORY_LIMIT) -> List[Commit]:
    """The commits that changed a file (renames followed), or a range of its lines (a symbol's history)."""
    relative = _inside(root, relative)
    if _git() is None:
        return []
    fmt = "--format=%x1e%h%x1f%an%x1f%ad%x1f%s"
    if start and end:   # -L prints each commit's diff for the range; only the headers are kept
        out = _run(root, "log", f"-n{limit}", fmt, "--date=short", f"-L{start},{end}:{relative}", check=False)
    else:
        out = _run(root, "log", f"-n{limit}", fmt, "--date=short", "--follow", "--", relative, check=False)
    if out.returncode != 0:
        if _nothing_to_show(out.stderr):
            return []
        raise ValueError(out.stderr.strip() or "git log failed.")
    commits = []
    for record in out.stdout.split("\x1e")[1:]:
        parts = record.split("\n", 1)[0].split("\x1f")
        if len(parts) == 4:
            commits.append(Commit(*parts))
    return commits[:limit]


def show(root: Path, commit: str, relative: str = "") -> Shown:
    """One commit: its message, author, date, the files it changed, and its diff for one path when asked."""
    commit = _commit_id(commit)
    out = _run(root, "show", "--format=%h%x1f%an%x1f%ad%x1f%B%x1e", "--date=short", "--numstat", "--no-color", commit, check=False)
    if out.returncode != 0:
        raise ValueError(out.stderr.strip() or "No such commit.")
    head, _, rest = out.stdout.partition("\x1e")
    parts = head.split("\x1f")
    if len(parts) != 4:
        raise ValueError("No such commit.")
    files = []
    for line in rest.splitlines():
        cells = line.split("\t")
        if len(cells) == 3:
            added, removed, path = cells
            path = re.sub(r"\{(.*?) => (.*?)\}", r"\2", path).replace("//", "/")   # A rename: "a/{Old.java => New.java}" is now New
            if " => " in path:
                path = path.split(" => ", 1)[1]
            files.append(ChangedFile(path, int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0))
    diff = ""
    if relative:
        relative = _inside(root, relative)
        diff = _run(root, "show", "--format=", "--no-color", "-M", commit, "--", relative, check=False).stdout
    return Shown(parts[0], parts[1], parts[2], parts[3].strip(), files, diff)
