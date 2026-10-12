"""
Rename a symbol with a preview (ADR-015, completed by ADR-025): every place the name would change,
each with its certainty, applied only where chosen and only where the text is still the old name.
Overrides and overridden methods are renamed together; so are a Java class's constructors and, when
the file is named after a public class, the file. Import lines are edits too. A new name that
collides with an existing one, or is a reserved word, is refused. Strings that contain the old name
are listed as mentions, never edited.
"""
import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.code.models import BY_NAME, RESOLVED, Symbol, Usage
from src.code.parser import JAVA, TYPE_KINDS
from src.code.store import CodeStore

DECLARATION = "declaration"
MAX_MENTIONS = 200
RESERVED = set("""
abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally
float for goto if implements import instanceof int interface long native new package private protected public return short
static strictfp super switch synchronized this throw throws transient try void volatile while true false null
var let function typeof delete in of yield await export debugger with null undefined
""".split())


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
class Mention:
    """A string on a line that contains the old name: shown for the user to judge, never edited."""
    key: str
    file_id: int
    path: str
    line: int
    col: int
    text: str


@dataclass
class Preview:
    symbol: Symbol
    new_name: str
    edits: List[Edit]
    also: List[Symbol]          # Methods renamed together (overrides, overridden); a class's constructors
    file_rename: Optional[Tuple[str, str]] = None   # (path now, path after) when the file is named after a public Java class
    collision: Optional[Symbol] = None              # An existing symbol the new name would clash with: applying is refused
    mentions: List[Mention] = field(default_factory=list)


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
    renamed_file: Optional[str] = None   # The file's new path, when it was renamed with the class


def _valid_name(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        raise ValueError("A name is letters, digits, _ and $, not starting with a digit.")
    if name in RESERVED:
        raise ValueError(f"`{name}` is a reserved word.")
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


def _constructors(store: CodeStore, symbol: Symbol) -> List[Symbol]:
    """A Java class's constructors: named after it, so renamed with it (and `new X()` through them)."""
    if symbol.language != JAVA or not symbol.is_type:
        return []
    return [m for m in store.members(symbol.id) if m.kind == "constructor" and m.name == symbol.name]


def collision(store: CodeStore, symbol: Symbol, new_name: str) -> Optional[Symbol]:
    """An existing symbol the new name would clash with, or None."""
    callable_ = symbol.kind in ("method", "constructor", "function")

    def clashes(other: Symbol) -> bool:
        if other.id == symbol.id or other.name != new_name:
            return False
        if callable_ and other.kind in ("method", "constructor", "function"):
            return other.params == symbol.params or other.params < 0 or symbol.params < 0
        return True
    if symbol.parent_id is not None:
        owner = store.symbol(symbol.parent_id)
        if owner is not None:
            hierarchy = store.hierarchy(owner)
            for type_ in [owner, *hierarchy.supertypes, *hierarchy.subtypes]:
                for member in store.members(type_.id):
                    if clashes(member):
                        return member
        return None
    for other in store.search_symbols(symbol.codebase_id, new_name, limit=200):
        if other.parent_id is not None or not clashes(other):
            continue
        if other.file_id == symbol.file_id:
            return other
        if symbol.language == JAVA and other.language == JAVA and other.is_type and symbol.is_type \
                and other.qualified.rsplit(".", 1)[0] == symbol.qualified.rsplit(".", 1)[0]:   # The same package
            return other
    return None


def _import_edits(store: CodeStore, symbol: Symbol) -> List[Tuple[int, str, int]]:
    """(file, path, line) of the import lines that name the symbol: Java single imports, TypeScript named imports."""
    found = []
    for row in store.conn.execute(
            "SELECT i.file_id, i.line, i.spec, i.names, i.is_static, f.path FROM code_imports i JOIN code_files f ON f.id = i.file_id "
            "WHERE i.target_file = ? ORDER BY f.path, i.line", (symbol.file_id,)):
        if symbol.language == JAVA:
            spec = row["spec"]
            if spec.endswith(".*"):
                continue
            if symbol.is_type and (spec == symbol.qualified or spec.startswith(symbol.qualified + ".")):
                found.append((row["file_id"], row["path"], row["line"]))
            elif row["is_static"] and symbol.parent_id is not None and spec == symbol.qualified.replace("#", "."):
                found.append((row["file_id"], row["path"], row["line"]))
        else:
            names = json.loads(row["names"] or "{}")
            if symbol.name in names.values() and symbol.parent_id is None:
                found.append((row["file_id"], row["path"], row["line"]))
    return found


def _mentions(store: CodeStore, symbol: Symbol, taken: Set[Tuple[int, int, int]]) -> List[Mention]:
    """Strings on lines of the codebase that contain the old name as a word, apart from the places edited."""
    pattern = re.compile(rf"""(["'`])(?:(?!\1)[^\n\\]|\\.)*?(?<![\w$]){re.escape(symbol.name)}(?![\w$])(?:(?!\1)[^\n\\]|\\.)*?\1""")
    mentions: List[Mention] = []
    for file, number, line in store.search_text(symbol.codebase_id, symbol.name, limit=5000):
        if file.language == "html":
            continue
        for match in pattern.finditer(line):
            col = match.start() + 1 + _name_col(match.group(0), symbol.name) - 1
            if (file.id, number, col) in taken:
                continue
            mentions.append(Mention(f"m:{file.id}:{number}:{col}", file.id, file.path, number, col, line))
            if len(mentions) >= MAX_MENTIONS:
                return mentions
    return mentions


def preview_rename(store: CodeStore, symbol: Symbol, new_name: str) -> Preview:
    new_name = _valid_name(new_name)
    if symbol.kind == "constructor":
        raise ValueError("A constructor is renamed through its class.")
    family = _family(store, symbol)
    constructors = _constructors(store, symbol)
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
    for member in family + constructors:
        lines = store.lines(member.file_id)
        declared_on = next((n for n in range(member.line, min(member.end_line, member.line + 10) + 1)
                            if n <= len(lines) and _name_col(lines[n - 1], symbol.name)), member.line)   # Annotations may come first
        add(member.file_id, member.path, declared_on, 0, DECLARATION, True, member.qualified)
        for usage in store.usages(member):
            add(usage.file_id, usage.path, usage.line, usage.col, usage.certainty, usage.certainty != BY_NAME)
    for file_id, path, line in _import_edits(store, symbol):
        add(file_id, path, line, 0, RESOLVED, True)
    ordered = sorted(edits.values(), key=lambda e: (e.path, e.line, e.col))
    file_rename = None
    if symbol.language == JAVA and symbol.is_type and symbol.parent_id is None and symbol.exported \
            and posixpath.basename(symbol.path) == f"{symbol.name}.java":
        file_rename = (symbol.path, posixpath.join(posixpath.dirname(symbol.path), f"{new_name}.java"))
    taken = {(e.file_id, e.line, e.col) for e in ordered}
    return Preview(symbol, new_name, ordered, [m for m in family + constructors if m.id != symbol.id], file_rename,
                   collision(store, symbol, new_name), _mentions(store, symbol, taken))


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


def apply_rename(store: CodeStore, symbol: Symbol, new_name: str, keys: Sequence[str], rename_file: bool = False) -> Result:
    new_name = _valid_name(new_name)
    preview = preview_rename(store, symbol, new_name)
    if preview.collision is not None:
        raise ValueError(f"`{new_name}` exists already: {preview.collision.qualified} ({preview.collision.location}). Choose another name.")
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
    renamed_file = None
    if rename_file and preview.file_rename is not None:
        current = next((f for f in files if f.id == symbol.file_id), None) or store.file(symbol.file_id)
        if current is not None and not _changed_on_disk(store, current):
            moved = store.rename_file(symbol.file_id, preview.file_rename[1], current.sha256)
            renamed_file = moved.path
            files = [moved if f.id == moved.id else f for f in files] if any(f.id == moved.id for f in files) else [*files, moved]
    return Result(files, sorted(skipped, key=lambda s: (s.path, s.line)), applied, renamed_file)
