"""
Rename a symbol with a preview (ADR-015): every place the name would change, each with its
certainty, applied only where chosen and only where the text is still the old name. Overrides and
overridden methods are renamed together.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set

from src.code.models import BY_NAME, Symbol, Usage
from src.code.store import CodeStore

DECLARATION = "declaration"


@dataclass
class Edit:
    key: str                    # "file:line:col"
    file_id: int
    path: str
    line: int
    col: int                    # 1-based column of the old name
    text: str                   # The line as it is
    certainty: str              # declaration, resolved, supertype, name
    selected: bool
    symbol: str = ""            # For declarations: which symbol


@dataclass
class Preview:
    symbol: Symbol
    new_name: str
    edits: List[Edit]
    also: List[Symbol]          # Methods renamed together (overrides, overridden)


@dataclass
class Skipped:
    key: str
    path: str
    line: int
    reason: str


@dataclass
class Result:
    files: list
    skipped: List[Skipped]
    edits_applied: int


def _valid_name(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        raise ValueError("A name is letters, digits, _ and $, not starting with a digit.")
    return name


def _name_col(text: str, name: str, hint_col: int = 0) -> int:
    """The 1-based column of `name` as a whole word on the line, nearest the hint; 0 when absent."""
    best = 0
    for match in re.finditer(rf"(?<![\w$]){re.escape(name)}(?![\w$])", text):
        col = match.start() + 1
        if hint_col and best and abs(col - hint_col) >= abs(best - hint_col):
            continue
        best = col
    return best


def _family(store: CodeStore, symbol: Symbol) -> List[Symbol]:
    """The symbol with what it overrides and what overrides it (transitively), renamed together."""
    if symbol.kind != "method":
        return [symbol]
    seen: Dict[int, Symbol] = {symbol.id: symbol}
    queue = [symbol]
    while queue:
        current = queue.pop()
        hierarchy = store.hierarchy(current)
        for other in hierarchy.overrides + hierarchy.overridden_by:
            if other.id not in seen:
                seen[other.id] = other
                queue.append(other)
    return list(seen.values())


def preview_rename(store: CodeStore, symbol: Symbol, new_name: str) -> Preview:
    new_name = _valid_name(new_name)
    family = _family(store, symbol)
    edits: Dict[str, Edit] = {}

    def add(file_id: int, path: str, line: int, col: int, certainty: str, selected: bool, which: str = "") -> None:
        lines = store.lines(file_id)
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        col = _name_col(text, symbol.name, col)
        if not col:
            return
        key = f"{file_id}:{line}:{col}"
        if key not in edits or certainty == DECLARATION:
            edits[key] = Edit(key, file_id, path, line, col, text, certainty, selected, which)
    for member in family:
        lines = store.lines(member.file_id)
        declared_on = next((n for n in range(member.line, min(member.end_line, member.line + 10) + 1)
                            if n <= len(lines) and _name_col(lines[n - 1], symbol.name)), member.line)   # Annotations may come first
        add(member.file_id, member.path, declared_on, 0, DECLARATION, True, member.qualified)
        for usage in store.usages(member):
            add(usage.file_id, usage.path, usage.line, usage.col, usage.certainty, usage.certainty != BY_NAME)
    ordered = sorted(edits.values(), key=lambda e: (e.path, e.line, e.col))
    return Preview(symbol, new_name, ordered, [m for m in family if m.id != symbol.id])


def _changed_on_disk(store: CodeStore, file) -> bool:
    import hashlib
    from pathlib import Path
    from src.code.store import _as_utf8
    codebase = store.get(file.codebase_id)
    try:
        data = _as_utf8((Path(codebase.root) / file.path).read_bytes())
    except OSError:
        return True
    return hashlib.sha256(data).hexdigest() != file.sha256


def apply_rename(store: CodeStore, symbol: Symbol, new_name: str, keys: Sequence[str]) -> Result:
    new_name = _valid_name(new_name)
    preview = preview_rename(store, symbol, new_name)
    chosen = {e.key: e for e in preview.edits if e.key in set(keys)}
    by_file: Dict[int, List[Edit]] = {}
    for edit in chosen.values():
        by_file.setdefault(edit.file_id, []).append(edit)
    skipped: List[Skipped] = []
    changes = []
    applied = 0
    for file_id, file_edits in by_file.items():
        file = store.file(file_id)
        if file is None:
            continue
        if _changed_on_disk(store, file):
            skipped += [Skipped(e.key, e.path, e.line, "the file changed on disk since it was indexed; save or rescan first") for e in file_edits]
            continue
        lines = store.text(file_id).split("\n")
        changed = False
        for edit in sorted(file_edits, key=lambda e: (e.line, -e.col)):   # Right to left on a line keeps columns valid
            line = lines[edit.line - 1] if 0 < edit.line <= len(lines) else ""
            start = edit.col - 1
            if line[start:start + len(symbol.name)] != symbol.name or (start > 0 and re.match(r"[\w$]", line[start - 1])) \
                    or re.match(r"[\w$]", line[start + len(symbol.name):start + len(symbol.name) + 1] or " "):
                skipped.append(Skipped(edit.key, edit.path, edit.line, "the text there is no longer the old name"))
                continue
            lines[edit.line - 1] = line[:start] + new_name + line[start + len(symbol.name):]
            changed = True
            applied += 1
        if changed:
            changes.append({"file_id": file_id, "sha256": file.sha256, "text": "\n".join(lines)})
    files = store.replace_in_files(symbol.codebase_id, changes) if changes else []
    return Result(files, sorted(skipped, key=lambda s: (s.path, s.line)), applied)
