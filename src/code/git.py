"""
Git status, diff and commit (ADR-015): the one program the app starts, run only with a codebase's
folder as its working directory and only for the operations here. No push, fetch, pull, checkout
or reset; nothing touching a remote.
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
