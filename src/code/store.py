"""
The code index: codebases read from folders on disk, kept alongside the document library.

A codebase is scanned where it is (nothing is copied except the text needed to search and show it).
Each source file is parsed into symbols, references, imports and HTTP endpoints (parser.py); then
every reference is linked to what it points to, the way an IDE would where that can be told without
compiling: through imports, declared types and scope. References that can't be linked are kept by
name, and reported as such, so a search for usages shows both what's certain and what's likely.
"""
import hashlib
import json
import os
import posixpath
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from src import config
from src.code import manifests
from src.code.models import (BY_NAME, RESOLVED, SUPERTYPE, CallNode, Codebase, CodeFile, Dependency, Endpoint,
                             Hierarchy, Symbol, Usage)
from src.code.parser import JAVA, TYPE_KINDS, ParsedFile, language_of, parse

READING, LINKING = "Reading files", "Linking references"
StageCallback = Callable[[str, int, int], None]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS codebases (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    root         TEXT NOT NULL UNIQUE,
    added_at     TEXT NOT NULL,
    indexed_at   TEXT NOT NULL DEFAULT '',
    file_count   INTEGER NOT NULL DEFAULT 0,
    symbol_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS code_files (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,      -- Relative to the root, forward slashes
    language    TEXT NOT NULL,
    package     TEXT NOT NULL,      -- Java package; the folder for JS/TS
    sha256      TEXT NOT NULL,
    lines       INTEGER NOT NULL,
    has_errors  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (codebase_id, path)
);
CREATE TABLE IF NOT EXISTS code_symbols (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    parent_id   INTEGER,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualified   TEXT NOT NULL,
    line        INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    signature   TEXT NOT NULL,
    params      INTEGER NOT NULL DEFAULT -1,
    exported    INTEGER NOT NULL DEFAULT 0,
    is_default  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS code_symbols_name ON code_symbols(codebase_id, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS code_symbols_file ON code_symbols(file_id, line);
CREATE INDEX IF NOT EXISTS code_symbols_parent ON code_symbols(parent_id);
-- target_id: the symbol it points to; target: an external API instead ("java.util.List#add", "axios#get").
-- Both empty: it couldn't be linked, and is matched by name.
CREATE TABLE IF NOT EXISTS code_refs (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    from_symbol INTEGER,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    receiver    TEXT NOT NULL DEFAULT '',
    args        INTEGER NOT NULL DEFAULT -1,
    line        INTEGER NOT NULL,
    col         INTEGER NOT NULL,
    target_id   INTEGER,
    target      TEXT
);
CREATE INDEX IF NOT EXISTS code_refs_name ON code_refs(codebase_id, name);
CREATE INDEX IF NOT EXISTS code_refs_target_id ON code_refs(target_id);
CREATE INDEX IF NOT EXISTS code_refs_target ON code_refs(codebase_id, target);
CREATE INDEX IF NOT EXISTS code_refs_from ON code_refs(from_symbol);
CREATE INDEX IF NOT EXISTS code_refs_file ON code_refs(file_id, line);
CREATE TABLE IF NOT EXISTS code_imports (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    line        INTEGER NOT NULL,
    spec        TEXT NOT NULL,
    is_static   INTEGER NOT NULL DEFAULT 0,
    names       TEXT NOT NULL DEFAULT '{}',   -- JS/TS: JSON of local name → imported name
    target_file INTEGER,                      -- The file in this codebase it imports from
    external    TEXT NOT NULL DEFAULT ''      -- Or the outside package: "java.util", "axios"
);
CREATE INDEX IF NOT EXISTS code_imports_file ON code_imports(file_id);
CREATE INDEX IF NOT EXISTS code_imports_target ON code_imports(target_file);
CREATE INDEX IF NOT EXISTS code_imports_external ON code_imports(codebase_id, external);
CREATE TABLE IF NOT EXISTS code_deps (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    manifest    TEXT NOT NULL,
    ecosystem   TEXT NOT NULL,
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    scope       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS code_endpoints (
    id          INTEGER PRIMARY KEY,
    codebase_id INTEGER NOT NULL REFERENCES codebases(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    symbol_id   INTEGER,
    side        TEXT NOT NULL,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    line        INTEGER NOT NULL,
    framework   TEXT NOT NULL
);
-- The text of every file (rowid = code_files.id), indexed by three-character runs so any piece of
-- an identifier or string can be searched for, in any case
CREATE VIRTUAL TABLE IF NOT EXISTS code_text USING fts5(content, tokenize = 'trigram');
"""

# Types every Java file sees without importing them
_JAVA_LANG = set("""
Object String StringBuilder StringBuffer CharSequence Number Integer Long Short Byte Double Float Boolean Character
Math System Thread Runnable Iterable Comparable Enum Record Class Void Process Runtime ThreadLocal AutoCloseable
Cloneable Throwable Exception RuntimeException Error IllegalArgumentException IllegalStateException
NullPointerException UnsupportedOperationException IndexOutOfBoundsException ArithmeticException ClassCastException
InterruptedException NumberFormatException ClassNotFoundException CloneNotSupportedException SecurityException
StackOverflowError OutOfMemoryError AssertionError Override Deprecated SuppressWarnings FunctionalInterface SafeVarargs
""".split())
_SCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
_SKIPPED_FILE = re.compile(r"\.min\.[cm]?js$|\.bundle\.js$|\.d\.[cm]?ts$")
# What a symbol of each kind can be referred to by, when only the name is known
_NAME_KINDS = {"method": ("call",), "constructor": ("new",), "function": ("call", "new", "jsx", "use"),
               "variable": ("use", "call"), "field": ()}
_TYPE_REF_KINDS = ("type", "new", "extends", "implements", "annotation", "jsx", "use")

Target = Union[int, str, None]   # A symbol id, an external name, or unknown


def normalize_path(path: str) -> str:
    """
    A URL path in one form, so the server's and the client's spelling can be compared: no host or
    query, and every variable part ("{id}", ":id", "${id}") as "{}".
    """
    path = re.sub(r"^[A-Za-z][\w+.-]*://[^/]*", "", path).split("?")[0].split("#")[0]
    path = re.sub(r"\$?\{[^}]*\}|(?<=/):\w+|<[^>]+>", "{}", path)
    segments = [segment for segment in path.split("/") if segment]
    while segments and segments[0] == "{}":   # A base URL held in a variable
        segments.pop(0)
    return "/" + "/".join(segments)


def paths_match(server: str, client: str) -> bool:
    """Whether a client's path reaches a server's route: equal, or one ends with the other (a base path)."""
    a, b = [s for s in server.split("/") if s], [s for s in client.split("/") if s]
    shared = min(len(a), len(b))
    if len(a) != len(b) and shared < 2:
        return False
    tail_a, tail_b = a[len(a) - shared:], b[len(b) - shared:]
    if shared and (all(s == "{}" for s in tail_a) or all(s == "{}" for s in tail_b)):
        return False
    return all(x == y or "{}" in (x, y) for x, y in zip(tail_a, tail_b))


def external_package(spec: str) -> str:
    """The package a JS/TS import names: "@scope/name/sub" → "@scope/name", "lodash/fp" → "lodash"."""
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


def java_package(qualified: str) -> str:
    """The package of a qualified Java name: everything before its first capitalised part."""
    parts = qualified.split(".")
    end = next((i for i, part in enumerate(parts) if part[:1].isupper() or part == "*"), len(parts))
    return ".".join(parts[:end])


class CodeStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.executescript(_SCHEMA)
        self._lines: Dict[int, List[str]] = {}   # File text by line, for the few files being looked at

    # ---- Codebases -------------------------------------------------------------------------

    def list_codebases(self) -> List[Codebase]:
        rows = self.conn.execute("SELECT * FROM codebases ORDER BY name COLLATE NOCASE").fetchall()
        return [Codebase(**dict(row)) for row in rows]

    def get(self, codebase_id: int) -> Optional[Codebase]:
        row = self.conn.execute("SELECT * FROM codebases WHERE id = ?", (codebase_id,)).fetchone()
        return Codebase(**dict(row)) if row else None

    def add(self, root: str, name: str = "") -> Codebase:
        """Registers a folder. Raises ValueError when it isn't a folder or is already registered."""
        folder = Path(root.strip().strip('"')).expanduser()
        if not root.strip() or not folder.is_dir():
            raise ValueError(f"“{root.strip()}” isn't a folder this app can read.")
        folder = folder.resolve()
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO codebases (name, root, added_at) VALUES (?, ?, ?)",
                    (" ".join(name.split()) or folder.name, str(folder), datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            raise ValueError("That folder is already in the list.") from None
        return self.get(cur.lastrowid)

    def remove(self, codebase_id: int) -> None:
        """Forgets a codebase and its index. The folder itself is never touched."""
        with self.conn:
            self.conn.execute("DELETE FROM code_text WHERE rowid IN (SELECT id FROM code_files WHERE codebase_id = ?)",
                              (codebase_id,))
            self.conn.execute("DELETE FROM codebases WHERE id = ?", (codebase_id,))
        self._lines.clear()

    # ---- Indexing --------------------------------------------------------------------------

    def index(self, codebase_id: int, on_progress: Optional[StageCallback] = None) -> Dict[str, int]:
        """
        Scans the folder: new and changed files are read again, removed ones forgotten, then every
        reference is linked afresh. Files are saved as they're read, so an interrupted scan carries
        on from there. Returns counts: files, changed, removed, symbols.
        """
        codebase = self.get(codebase_id)
        if codebase is None:
            raise ValueError("That codebase is no longer in the list.")
        root = Path(codebase.root)
        if not root.is_dir():
            raise ValueError(f"The folder {codebase.root} can't be read. If it was moved, remove it and add it again.")

        sources, build_files, configs = _scan(root)
        known = {row["path"]: (row["id"], row["sha256"]) for row in self.conn.execute(
            "SELECT id, path, sha256 FROM code_files WHERE codebase_id = ?", (codebase_id,))}
        changed = 0
        for done, relative in enumerate(sources, 1):
            try:
                data = _as_utf8((root / relative).read_bytes())
            except OSError:
                continue   # Unreadable now: left as it was last indexed
            sha256 = hashlib.sha256(data).hexdigest()
            if known.get(relative, (None, None))[1] != sha256:
                with self.conn:
                    self._store_file(codebase_id, relative, data, sha256, known.get(relative, (None,))[0])
                changed += 1
            if on_progress and (done % 20 == 0 or done == len(sources)):
                on_progress(READING, done, len(sources))

        present = set(sources)
        removed = [file_id for path, (file_id, _) in known.items() if path not in present]
        with self.conn:
            for file_id in removed:
                self._delete_file(file_id)
            self.conn.execute("DELETE FROM code_deps WHERE codebase_id = ?", (codebase_id,))
            for relative in build_files:
                declared = manifests.read_manifest(posixpath.basename(relative), _read_text(root / relative))
                self.conn.executemany(
                    "INSERT INTO code_deps (codebase_id, manifest, ecosystem, name, version, scope) VALUES (?, ?, ?, ?, ?, ?)",
                    [(codebase_id, relative, *entry) for entry in declared],
                )
        aliases = []
        for relative in configs:
            found = manifests.read_aliases(_read_text(root / relative))
            if found:
                aliases.append((posixpath.dirname(relative), *found))
        if changed or removed or not codebase.indexed_at:   # Otherwise every link still stands
            _Linker(self.conn, codebase_id, aliases).run(on_progress)

        files, symbols = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM code_files WHERE codebase_id = ?1), "
            "(SELECT COUNT(*) FROM code_symbols WHERE codebase_id = ?1)", (codebase_id,)).fetchone()
        with self.conn:
            self.conn.execute("UPDATE codebases SET indexed_at = ?, file_count = ?, symbol_count = ? WHERE id = ?",
                              (datetime.now().isoformat(timespec="seconds"), files, symbols, codebase_id))
        self._lines.clear()
        return {"files": files, "changed": changed, "removed": len(removed), "symbols": symbols}

    def _delete_file(self, file_id: int) -> None:
        self.conn.execute("DELETE FROM code_text WHERE rowid = ?", (file_id,))
        self.conn.execute("DELETE FROM code_files WHERE id = ?", (file_id,))   # The rest cascades

    def _store_file(self, codebase_id: int, path: str, data: bytes, sha256: str, old_id: Optional[int]) -> None:
        if old_id is not None:
            self._delete_file(old_id)
        text = data.decode("utf-8", "replace")   # Line numbers match the parser's: both count "\n"
        parsed: ParsedFile = parse(path, data)
        package = parsed.package if parsed.language == JAVA else posixpath.dirname(path)
        file_id = self.conn.execute(
            "INSERT INTO code_files (codebase_id, path, language, package, sha256, lines, has_errors) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (codebase_id, path, parsed.language, package, sha256, text.count("\n") + 1, int(parsed.has_errors)),
        ).lastrowid
        self.conn.execute("INSERT INTO code_text (rowid, content) VALUES (?, ?)", (file_id, text))

        first = self.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM code_symbols").fetchone()[0]
        symbol_id = lambda index: None if index is None else first + index   # Parsed symbols refer to each other by position
        self.conn.executemany(
            "INSERT INTO code_symbols (id, codebase_id, file_id, parent_id, kind, name, qualified, line, end_line, "
            "signature, params, exported, is_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(first + i, codebase_id, file_id, symbol_id(s.parent), s.kind, s.name, s.qualified, s.line, s.end_line,
              s.signature, s.params, int(s.exported), int(s.default)) for i, s in enumerate(parsed.symbols)],
        )
        self.conn.executemany(
            "INSERT INTO code_refs (codebase_id, file_id, from_symbol, kind, name, receiver, args, line, col) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(codebase_id, file_id, symbol_id(r.scope), r.kind, r.name, r.receiver, r.args, r.line, r.col)
             for r in parsed.refs],
        )
        self.conn.executemany(
            "INSERT INTO code_imports (codebase_id, file_id, line, spec, is_static, names) VALUES (?, ?, ?, ?, ?, ?)",
            [(codebase_id, file_id, i.line, i.spec, int(i.static), json.dumps(i.names)) for i in parsed.imports],
        )
        self.conn.executemany(
            "INSERT INTO code_endpoints (codebase_id, file_id, symbol_id, side, method, path, line, framework) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(codebase_id, file_id, symbol_id(e.scope), e.side, e.method, e.path, e.line, e.framework)
             for e in parsed.endpoints],
        )

    # ---- Files -----------------------------------------------------------------------------

    def files(self, codebase_id: int) -> List[CodeFile]:
        rows = self.conn.execute("SELECT * FROM code_files WHERE codebase_id = ? ORDER BY path", (codebase_id,)).fetchall()
        return [_file(row) for row in rows]

    def file(self, file_id: int) -> Optional[CodeFile]:
        row = self.conn.execute("SELECT * FROM code_files WHERE id = ?", (file_id,)).fetchone()
        return _file(row) if row else None

    def lines(self, file_id: int) -> List[str]:
        """A file's text as it was when indexed, by line."""
        if file_id not in self._lines:
            if len(self._lines) >= 64:
                self._lines.clear()
            row = self.conn.execute("SELECT content FROM code_text WHERE rowid = ?", (file_id,)).fetchone()
            self._lines[file_id] = row[0].split("\n") if row else []
        return self._lines[file_id]

    def _line(self, file_id: int, line: int) -> str:
        lines = self.lines(file_id)
        return lines[line - 1].strip() if 0 < line <= len(lines) else ""

    def outline(self, file_id: int) -> List[Symbol]:
        return self._symbols("s.file_id = ? ORDER BY s.line, s.id", (file_id,))

    def imports_of(self, file_id: int) -> List[sqlite3.Row]:
        """What a file imports: rows with spec, line, external, and target_path for files in the codebase."""
        return self.conn.execute(
            "SELECT i.*, f.path AS target_path FROM code_imports i LEFT JOIN code_files f ON f.id = i.target_file "
            "WHERE i.file_id = ? ORDER BY i.line", (file_id,)).fetchall()

    def imported_by(self, file_id: int) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT i.line, i.spec, f.id AS file_id, f.path FROM code_imports i JOIN code_files f ON f.id = i.file_id "
            "WHERE i.target_file = ? ORDER BY f.path", (file_id,)).fetchall()

    # ---- Symbols ---------------------------------------------------------------------------

    def _symbols(self, where: str, params: Sequence) -> List[Symbol]:
        rows = self.conn.execute(
            f"SELECT s.*, f.path, f.language FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE {where}",
            params).fetchall()
        return [_symbol(row) for row in rows]

    def symbol(self, symbol_id: Optional[int]) -> Optional[Symbol]:
        found = self._symbols("s.id = ?", (symbol_id,)) if symbol_id is not None else []
        return found[0] if found else None

    def symbol_at(self, file_id: int, line: int) -> Optional[Symbol]:
        """The innermost symbol whose declaration covers a line."""
        found = self._symbols("s.file_id = ? AND s.line <= ? AND s.end_line >= ? ORDER BY s.line DESC, s.id DESC LIMIT 1",
                              (file_id, line, line))
        return found[0] if found else None

    def members(self, symbol_id: int) -> List[Symbol]:
        return self._symbols("s.parent_id = ? ORDER BY s.line", (symbol_id,))

    def search_symbols(self, codebase_id: int, text: str, kinds: Optional[Sequence[str]] = None,
                       limit: int = config.CODE_MAX_RESULTS) -> List[Symbol]:
        """Symbols whose name (or qualified name) contains the text: exact names first, then prefixes."""
        text = text.strip()
        if not text:
            return []
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = "s.codebase_id = ? AND (s.name LIKE ? ESCAPE '\\' OR s.qualified LIKE ? ESCAPE '\\')"
        params: list = [codebase_id, like, like]
        if kinds:
            where += f" AND s.kind IN ({', '.join('?' * len(kinds))})"
            params.extend(kinds)
        where += (" ORDER BY (s.name = ? COLLATE NOCASE) DESC, (s.name LIKE ? ESCAPE '\\') DESC, "
                  "(s.name LIKE ? ESCAPE '\\') DESC, LENGTH(s.name), s.qualified LIMIT ?")
        return self._symbols(where, [*params, text, like[1:], like, limit])

    def search_text(self, codebase_id: int, text: str, limit: int = config.CODE_MAX_RESULTS) -> List[Tuple[CodeFile, int, str]]:
        """(file, line number, line) for every line containing the text, in any case."""
        text = text.strip()
        if not text:
            return []
        if len(text) >= 3:   # The index works on runs of three characters
            rows = self.conn.execute(
                "SELECT f.* FROM code_text t JOIN code_files f ON f.id = t.rowid "
                "WHERE t.content MATCH ? AND f.codebase_id = ? ORDER BY f.path",
                ('"' + text.replace('"', '""') + '"', codebase_id)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT f.* FROM code_text t JOIN code_files f ON f.id = t.rowid "
                "WHERE f.codebase_id = ? AND INSTR(LOWER(t.content), ?) > 0 ORDER BY f.path",
                (codebase_id, text.lower())).fetchall()
        hits, wanted = [], text.lower()
        for row in rows:
            for number, line in enumerate(self.lines(row["id"]), 1):
                if wanted in line.lower():
                    hits.append((_file(row), number, line.rstrip()))
                    if len(hits) >= limit:
                        return hits
        return hits

    # ---- Usages and calls ------------------------------------------------------------------

    def _usages(self, where: str, params: Sequence, certainty: str = RESOLVED, limit: int = config.CODE_MAX_RESULTS) -> List[Usage]:
        rows = self.conn.execute(
            f"SELECT r.*, f.path, s.qualified AS from_name FROM code_refs r JOIN code_files f ON f.id = r.file_id "
            f"LEFT JOIN code_symbols s ON s.id = r.from_symbol WHERE {where} ORDER BY f.path, r.line, r.col LIMIT ?",
            [*params, limit]).fetchall()
        return [
            Usage(ref_id=row["id"], kind=row["kind"], name=row["name"], line=row["line"], col=row["col"],
                  file_id=row["file_id"], path=row["path"], text=self._line(row["file_id"], row["line"]),
                  from_symbol=row["from_symbol"], from_name=row["from_name"] or "", certainty=certainty,
                  target_id=row["target_id"], target=row["target"] or "")
            for row in rows
        ]

    def usages(self, symbol: Symbol, kinds: Optional[Sequence[str]] = None) -> List[Usage]:
        """
        Everywhere a symbol is referred to: links that were followed for certain; for a method, calls
        made through a supertype's method it overrides; and references that only agree by name.
        """
        kind_filter = f" AND r.kind IN ({', '.join('?' * len(kinds))})" if kinds else ""
        extra = list(kinds or [])
        found = self._usages(f"r.target_id = ?{kind_filter}", [symbol.id, *extra])
        overridden = [s.id for s in self.hierarchy(symbol).overrides] if symbol.kind == "method" else []
        if overridden:
            marks = ", ".join("?" * len(overridden))
            found += self._usages(f"r.target_id IN ({marks}){kind_filter}", [*overridden, *extra], SUPERTYPE)

        name_kinds = _TYPE_REF_KINDS if symbol.is_type else _NAME_KINDS.get(symbol.kind, ())
        name_kinds = [k for k in name_kinds if not kinds or k in kinds]
        if name_kinds:
            where = (f"r.codebase_id = ? AND r.name = ? AND r.target_id IS NULL AND r.target IS NULL "
                     f"AND r.kind IN ({', '.join('?' * len(name_kinds))}) AND (f.language = 'java') = ?")
            params: list = [symbol.codebase_id, symbol.name, *name_kinds, int(symbol.language == JAVA)]
            if symbol.language == JAVA and symbol.is_callable and symbol.params >= 0:
                where += " AND r.args IN (-1, ?)"   # An overload with another number of arguments isn't this one
                params.append(symbol.params)
            found += self._usages(where, params, BY_NAME)
        return found

    def callers(self, symbol: Symbol) -> List[Usage]:
        return self.usages(symbol, kinds=("call", "new", "jsx"))

    def callees(self, symbol: Symbol) -> List[Usage]:
        """Calls made in a symbol's body (for a type: in all its members)."""
        scope = [symbol.id] + ([m.id for m in self.members(symbol.id)] if symbol.is_type else [])
        return self._usages(f"r.from_symbol IN ({', '.join('?' * len(scope))}) AND r.kind IN ('call', 'new', 'jsx')", scope)

    def call_tree(self, symbol: Symbol, callers: bool, depth: int = config.CODE_CALL_DEPTH,
                  width: int = config.CODE_CALL_WIDTH) -> List[CallNode]:
        """Who calls a symbol (and who calls them…), or what it calls, following certain links only."""
        def step(symbol_id: int, level: int, path: Tuple[int, ...]) -> List[CallNode]:
            if callers:
                rows = self.conn.execute(
                    "SELECT from_symbol AS other, MIN(line) AS line FROM code_refs WHERE target_id = ? "
                    "AND kind IN ('call', 'new', 'jsx') AND from_symbol IS NOT NULL GROUP BY from_symbol LIMIT ?",
                    (symbol_id, width)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT target_id AS other, MIN(line) AS line FROM code_refs WHERE from_symbol = ? "
                    "AND kind IN ('call', 'new', 'jsx') AND target_id IS NOT NULL GROUP BY target_id ORDER BY line LIMIT ?",
                    (symbol_id, width)).fetchall()
            nodes = []
            for row in rows:
                other = self.symbol(row["other"])
                if other is None:
                    continue
                stop = level >= depth or other.id in path
                children = () if stop else tuple(step(other.id, level + 1, (*path, other.id)))
                nodes.append(CallNode(other, row["line"], children, truncated=stop))
            return sorted(nodes, key=lambda n: (n.symbol.path, n.symbol.line))
        return step(symbol.id, 1, (symbol.id,))

    def hierarchy(self, symbol: Symbol) -> Hierarchy:
        """A type's supertypes and subtypes; for a method, what it overrides and what overrides it."""
        owner = symbol if symbol.is_type else self.symbol(symbol.parent_id)
        if owner is None or not owner.is_type:
            return Hierarchy([], [], [], [], [])
        ups, external = self._supertypes(owner.id)
        downs = self._subtypes(owner.id)
        if symbol.is_type:
            return Hierarchy(ups, external, downs, [], [])

        def same_method(types: List[Symbol]) -> List[Symbol]:
            if not types:
                return []
            marks = ", ".join("?" * len(types))
            return self._symbols(f"s.parent_id IN ({marks}) AND s.name = ? AND s.kind = 'method' "
                                 f"AND (s.params = ? OR ? < 0) ORDER BY f.path", [*[t.id for t in types], symbol.name,
                                                                                 symbol.params, symbol.params])
        return Hierarchy(ups, external, downs, same_method(ups), same_method(downs))

    def _supertypes(self, type_id: int) -> Tuple[List[Symbol], List[str]]:
        found: Dict[int, Symbol] = {}
        external: List[str] = []
        queue = [type_id]
        while queue:
            current = queue.pop()
            for row in self.conn.execute("SELECT target_id, target FROM code_refs WHERE from_symbol = ? "
                                         "AND kind IN ('extends', 'implements')", (current,)):
                if row["target_id"] is not None and row["target_id"] not in found and row["target_id"] != type_id:
                    parent = self.symbol(row["target_id"])
                    if parent:
                        found[parent.id] = parent
                        queue.append(parent.id)
                elif row["target"] and row["target"] not in external:
                    external.append(row["target"])
        return list(found.values()), external

    def _subtypes(self, type_id: int) -> List[Symbol]:
        found: Dict[int, Symbol] = {}
        queue = [type_id]
        while queue:
            current = queue.pop()
            for row in self.conn.execute("SELECT from_symbol FROM code_refs WHERE target_id = ? "
                                         "AND kind IN ('extends', 'implements') AND from_symbol IS NOT NULL", (current,)):
                if row[0] not in found and row[0] != type_id:
                    child = self.symbol(row[0])
                    if child:
                        found[child.id] = child
                        queue.append(child.id)
        return sorted(found.values(), key=lambda s: s.qualified)

    def ref_at(self, file_id: int, line: int, col: int) -> Optional[Usage]:
        """The reference written at a position (1-based line and column), if any."""
        found = [u for u in self._usages("r.file_id = ? AND r.line = ?", (file_id, line))
                 if u.col <= col <= u.col + len(u.name)]
        # A call and a plain use can share a name's position: the more specific one says more
        return min(found, key=lambda u: (u.kind == "use", u.target_id is None and not u.target), default=None)

    def declared_at(self, file_id: int, line: int, col: int) -> Optional[Symbol]:
        """The symbol whose name is written at a position on its declaration's first line."""
        text = self.lines(file_id)[line - 1] if 0 < line <= len(self.lines(file_id)) else ""
        for symbol in self._symbols("s.file_id = ? AND s.line = ? ORDER BY s.id DESC", (file_id, line)):
            for match in re.finditer(rf"(?<![\w$]){re.escape(symbol.name)}(?![\w$])", text):
                if match.start() + 1 <= col <= match.end() + 1:
                    return symbol
        return None

    def named(self, codebase_id: int, usage: Usage, java: bool, limit: int = 20) -> List[Symbol]:
        """Symbols a reference that couldn't be linked may mean: the same name, of a fitting kind and language."""
        kinds = [kind for kind, ref_kinds in _NAME_KINDS.items() if usage.kind in ref_kinds]
        if usage.kind in _TYPE_REF_KINDS:
            kinds += TYPE_KINDS
        if not kinds:
            return []
        return self._symbols(
            f"s.codebase_id = ? AND s.name = ? AND s.kind IN ({', '.join('?' * len(kinds))}) "
            f"AND (f.language = 'java') = ? ORDER BY f.path, s.line LIMIT ?",
            [codebase_id, usage.name, *kinds, int(java), limit])

    def refs_on_lines(self, file_id: int, first: int, last: int) -> List[Usage]:
        """References made on a range of a file's lines, to follow from the code being read."""
        return self._usages("r.file_id = ? AND r.line BETWEEN ? AND ? AND (r.target_id IS NOT NULL OR r.target IS NOT NULL)",
                            (file_id, first, last))

    # ---- Dependencies ----------------------------------------------------------------------

    def declared(self, codebase_id: int) -> List[Dependency]:
        used = dict(self.conn.execute(
            "SELECT external, COUNT(DISTINCT file_id) FROM code_imports WHERE codebase_id = ? AND external != '' "
            "GROUP BY external", (codebase_id,)).fetchall())
        rows = self.conn.execute("SELECT * FROM code_deps WHERE codebase_id = ? ORDER BY ecosystem, name, manifest",
                                 (codebase_id,)).fetchall()
        return [Dependency(row["manifest"], row["ecosystem"], row["name"], row["version"], row["scope"],
                           used.get(row["name"], 0) if row["ecosystem"] == "npm" else None) for row in rows]

    def external_packages(self, codebase_id: int) -> List[Tuple[str, int, int]]:
        """(package, files importing it, references to its members), most widely used first."""
        files = dict(self.conn.execute(
            "SELECT external, COUNT(DISTINCT file_id) FROM code_imports WHERE codebase_id = ? AND external != '' "
            "GROUP BY external", (codebase_id,)).fetchall())
        uses: Dict[str, int] = defaultdict(int)
        for target, count in self.conn.execute(
                "SELECT target, COUNT(*) FROM code_refs WHERE codebase_id = ? AND target IS NOT NULL GROUP BY target",
                (codebase_id,)):
            uses[_package_of_target(target)] += count
        packages = set(files) | {p for p in uses if p}
        return sorted(((p, files.get(p, 0), uses.get(p, 0)) for p in packages), key=lambda row: (-row[1], -row[2], row[0]))

    def package_imports(self, codebase_id: int, package: str) -> List[sqlite3.Row]:
        """Every import of an external package: rows with path, file_id, line, spec."""
        return self.conn.execute(
            "SELECT i.line, i.spec, f.id AS file_id, f.path FROM code_imports i JOIN code_files f ON f.id = i.file_id "
            "WHERE i.codebase_id = ? AND i.external = ? ORDER BY f.path, i.line", (codebase_id, package)).fetchall()

    def external_members(self, codebase_id: int, package: str) -> List[Tuple[str, int]]:
        """(API member, times used) for an external package: "java.util.List#add", "axios#get"."""
        rows = self.conn.execute(
            "SELECT target, COUNT(*) FROM code_refs WHERE codebase_id = ? AND target >= ? AND target < ? GROUP BY target",
            (codebase_id, package, package + "￿")).fetchall()
        return sorted(((t, n) for t, n in rows if _package_of_target(t) == package), key=lambda row: (-row[1], row[0]))

    def external_usages(self, codebase_id: int, target: str) -> List[Usage]:
        return self._usages("r.codebase_id = ? AND r.target = ?", (codebase_id, target))

    def internal_dependencies(self, codebase_id: int) -> List[Tuple[str, str, int]]:
        """(package, package it depends on, references between them): Java packages, JS/TS folders."""
        rows = self.conn.execute(
            """
            SELECT f1.package, f2.package, COUNT(*) FROM code_refs r
            JOIN code_files f1 ON f1.id = r.file_id
            JOIN code_symbols s ON s.id = r.target_id JOIN code_files f2 ON f2.id = s.file_id
            WHERE r.codebase_id = ? AND f1.package != f2.package GROUP BY f1.package, f2.package
            """, (codebase_id,)).fetchall()
        return sorted(((a or "(root)", b or "(root)", n) for a, b, n in rows), key=lambda row: (-row[2], row[0], row[1]))

    def package_links(self, codebase_id: int, source: str, target: str) -> List[Usage]:
        """The references behind one package-to-package dependency."""
        source, target = ("" if p == "(root)" else p for p in (source, target))
        return self._usages(
            "r.codebase_id = ? AND f.package = ? AND r.target_id IN (SELECT s2.id FROM code_symbols s2 "
            "JOIN code_files f2 ON f2.id = s2.file_id WHERE s2.codebase_id = ? AND f2.package = ?)",
            (codebase_id, source, codebase_id, target))

    # ---- HTTP endpoints --------------------------------------------------------------------

    def endpoints(self, codebase_id: int) -> Tuple[List[Tuple[Endpoint, List[Endpoint]]], List[Endpoint]]:
        """
        (routes the code serves, each with the client calls that reach it; client calls matching no
        route here). A call matches by method and path, with variable parts matching anything.
        """
        rows = self.conn.execute(
            "SELECT e.*, f.path AS file_path, s.qualified AS symbol_name FROM code_endpoints e "
            "JOIN code_files f ON f.id = e.file_id LEFT JOIN code_symbols s ON s.id = e.symbol_id "
            "WHERE e.codebase_id = ? ORDER BY e.path, e.method, f.path", (codebase_id,)).fetchall()
        endpoints = [Endpoint(row["id"], row["side"], row["method"], row["path"], row["line"], row["file_id"],
                              row["file_path"], row["symbol_id"], row["symbol_name"] or "", row["framework"])
                     for row in rows]
        servers = [e for e in endpoints if e.side == "server"]
        clients = [e for e in endpoints if e.side == "client"]
        normal = {e.id: normalize_path(e.path) for e in endpoints}
        matched: Set[int] = set()
        served = []
        for server in servers:
            calls = [c for c in clients
                     if (server.method == c.method or "ANY" in (server.method, c.method))
                     and paths_match(normal[server.id], normal[c.id])]
            matched.update(c.id for c in calls)
            served.append((server, calls))
        return served, [c for c in clients if c.id not in matched]


def _file(row: sqlite3.Row) -> CodeFile:
    return CodeFile(row["id"], row["codebase_id"], row["path"], row["language"], row["package"], row["lines"],
                    bool(row["has_errors"]))


def _symbol(row: sqlite3.Row) -> Symbol:
    return Symbol(id=row["id"], codebase_id=row["codebase_id"], file_id=row["file_id"], parent_id=row["parent_id"],
                  kind=row["kind"], name=row["name"], qualified=row["qualified"], line=row["line"],
                  end_line=row["end_line"], signature=row["signature"], params=row["params"],
                  exported=bool(row["exported"]), path=row["path"], language=row["language"])


def _package_of_target(target: str) -> str:
    """The external package an API member belongs to: "java.util.List#add" → "java.util", "axios#get" → "axios"."""
    owner = target.split("#")[0]
    if owner.startswith(("@", "node:")) or "/" in owner or not re.search(r"\.[A-Z]", "." + owner):
        return external_package(owner)
    return java_package(owner)


def _as_utf8(data: bytes) -> bytes:
    """Source bytes as plain UTF-8 with "\n" line endings: Windows editors add byte-order marks, UTF-16 and CRLF."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        data = data.decode("utf-16", "replace").encode("utf-8")
    return data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _scan(root: Path) -> Tuple[List[str], List[str], List[str]]:
    """Source files, build files and tsconfig/jsconfig files under a folder, as sorted relative paths."""
    sources, build_files, configs = [], [], []
    for folder, folders, names in os.walk(root):
        # Build output, dependencies and tool folders hold no source of the project's own
        folders[:] = sorted(d for d in folders if d not in config.CODE_SKIP_FOLDERS and not d.startswith("."))
        for name in sorted(names):
            relative = (Path(folder) / name).relative_to(root).as_posix()
            if name in manifests.MANIFESTS:
                build_files.append(relative)
            elif name in manifests.SCRIPT_CONFIGS:
                configs.append(relative)
            elif language_of(name) and not _SKIPPED_FILE.search(name):
                try:
                    if (Path(folder) / name).stat().st_size <= config.CODE_MAX_FILE_BYTES:
                        sources.append(relative)
                except OSError:
                    pass
    return sources, build_files, configs


class _Linker:
    """Links every reference in a codebase to the symbol or external API it points to."""

    def __init__(self, conn: sqlite3.Connection, codebase_id: int, aliases: List[Tuple[str, str, Dict[str, List[str]]]]):
        self.conn, self.codebase_id = conn, codebase_id
        self.aliases = sorted(aliases, key=lambda a: -len(a[0]))   # Nearest config first

    def run(self, on_progress: Optional[StageCallback]) -> None:
        conn, cid = self.conn, self.codebase_id
        self.files = {row["id"]: row for row in conn.execute("SELECT * FROM code_files WHERE codebase_id = ?", (cid,))}
        self.by_path = {row["path"]: file_id for file_id, row in self.files.items()}
        self.symbols = {row["id"]: row for row in conn.execute("SELECT * FROM code_symbols WHERE codebase_id = ?", (cid,))}
        self.members: Dict[int, Dict[str, List[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
        self.top: Dict[int, Dict[str, int]] = defaultdict(dict)        # File → its top-level symbols by name
        self.default: Dict[int, int] = {}                              # File → its default export
        self.java_types: Dict[str, int] = {}                           # Qualified name → type
        self.java_packages: Set[str] = set()
        for symbol_id, s in sorted(self.symbols.items()):
            java = self.files[s["file_id"]]["language"] == JAVA
            if s["parent_id"] is not None:
                self.members[s["parent_id"]][s["name"]].append(s)
            elif not java:
                self.top[s["file_id"]].setdefault(s["name"], symbol_id)
                if s["is_default"]:
                    self.default.setdefault(s["file_id"], symbol_id)
            if java and s["kind"] in TYPE_KINDS:
                self.java_types.setdefault(s["qualified"], symbol_id)
        self.java_packages = {f["package"] for f in self.files.values() if f["language"] == JAVA}

        self._link_imports()
        refs = conn.execute("SELECT id, file_id, from_symbol, kind, name, receiver, args FROM code_refs "
                            "WHERE codebase_id = ? ORDER BY (kind IN ('extends', 'implements')) DESC, id", (cid,)).fetchall()
        self.supers: Dict[int, List[int]] = defaultdict(list)          # Type → the types it extends or implements
        self.external_supers: Dict[int, List[str]] = defaultdict(list)
        updates = []
        for done, ref in enumerate(refs, 1):
            target = self._link(ref)
            if ref["kind"] in ("extends", "implements") and ref["from_symbol"] is not None:
                if isinstance(target, int):
                    self.supers[ref["from_symbol"]].append(target)
                elif target:
                    self.external_supers[ref["from_symbol"]].append(target)
            updates.append((target if isinstance(target, int) else None, target if isinstance(target, str) else None, ref["id"]))
            if on_progress and (done % 5000 == 0 or done == len(refs)):
                on_progress(LINKING, done, len(refs))
        with conn:
            conn.executemany("UPDATE code_refs SET target_id = ?, target = ? WHERE id = ?", updates)

    # -- Imports ---------------------------------------------------------------------------------

    def _link_imports(self) -> None:
        self.java_single: Dict[int, Dict[str, str]] = defaultdict(dict)      # File → simple name → qualified
        self.java_wild: Dict[int, List[str]] = defaultdict(list)
        self.java_static: Dict[int, Dict[str, str]] = defaultdict(dict)      # File → member → its type
        self.java_static_wild: Dict[int, List[str]] = defaultdict(list)
        self.bindings: Dict[int, Dict[str, Tuple[Optional[int], str, str]]] = defaultdict(dict)  # Local → (file, package, imported)
        updates = []
        for row in self.conn.execute("SELECT * FROM code_imports WHERE codebase_id = ?", (self.codebase_id,)).fetchall():
            file_id, spec = row["file_id"], row["spec"]
            target_file, external = None, ""
            if self.files[file_id]["language"] == JAVA:
                wildcard = spec.endswith(".*")
                name = spec[:-2] if wildcard else spec
                type_name = name if (wildcard or not row["is_static"]) else name.rsplit(".", 1)[0]
                if row["is_static"]:
                    if wildcard:
                        self.java_static_wild[file_id].append(name)
                    else:
                        self.java_static[file_id][name.rsplit(".", 1)[1]] = type_name
                elif wildcard:
                    self.java_wild[file_id].append(name)
                else:
                    self.java_single[file_id][name.rsplit(".", 1)[-1]] = name
                if type_name in self.java_types:
                    target_file = self.symbols[self.java_types[type_name]]["file_id"]
                elif not (wildcard and not row["is_static"] and name in self.java_packages):
                    external = java_package(spec)
            else:
                target_file = self._module(self.files[file_id]["path"], spec)
                if target_file is None and not spec.startswith((".", "/")):
                    external = external_package(spec)
                for local, imported in json.loads(row["names"]).items():
                    self.bindings[file_id][local] = (target_file, external, imported)
            updates.append((target_file, external, row["id"]))
        with self.conn:
            self.conn.executemany("UPDATE code_imports SET target_file = ?, external = ? WHERE id = ?", updates)

    def _module(self, importer: str, spec: str) -> Optional[int]:
        """The file a JS/TS import refers to, trying the extensions and index files Node and bundlers do."""
        bases = []
        if spec.startswith("."):
            bases.append(posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec)))
        elif spec.startswith("/"):
            bases.append(spec.lstrip("/"))
        else:
            for folder, base_url, paths in self.aliases:
                if folder and not importer.startswith(folder + "/"):
                    continue
                for pattern, replacements in paths.items():
                    prefix, star, suffix = pattern.partition("*")
                    if spec.startswith(prefix) and spec.endswith(suffix) and (star or spec == pattern):
                        middle = spec[len(prefix):len(spec) - len(suffix)] if star else ""
                        bases += [posixpath.normpath(posixpath.join(folder, base_url, r.replace("*", middle)))
                                  for r in replacements]
                bases.append(posixpath.normpath(posixpath.join(folder, base_url, spec)))
        for base in bases:
            candidates = [base] + [base + ext for ext in _SCRIPT_EXTENSIONS] \
                + [posixpath.join(base, "index" + ext) for ext in _SCRIPT_EXTENSIONS]
            if re.search(r"\.[cm]?js$", base):   # TypeScript sources are imported by their compiled name
                candidates += [re.sub(r"\.([cm]?)js$", r".\1ts", base), re.sub(r"\.js$", ".tsx", base)]
            for candidate in candidates:
                if candidate in self.by_path:
                    return self.by_path[candidate]
        return None

    # -- References ------------------------------------------------------------------------------

    def _enclosing_type(self, symbol_id: Optional[int]) -> Optional[int]:
        while symbol_id is not None and symbol_id in self.symbols:
            if self.symbols[symbol_id]["kind"] in TYPE_KINDS:
                return symbol_id
            symbol_id = self.symbols[symbol_id]["parent_id"]
        return None

    def _method(self, type_id: int, name: str, args: int, kinds: Tuple[str, ...] = ("method", "function", "field"),
                seen: Optional[Set[int]] = None) -> Optional[int]:
        """A member of a type or of the types it extends, preferring one taking this many arguments."""
        seen = seen if seen is not None else set()
        if type_id in seen:
            return None
        seen.add(type_id)
        candidates = [m for m in self.members[type_id].get(name, []) if m["kind"] in kinds]
        if candidates:
            return next((m["id"] for m in candidates if args >= 0 and m["params"] == args), candidates[0]["id"])
        for parent in self.supers.get(type_id, []):
            found = self._method(parent, name, args, kinds, seen)
            if found is not None:
                return found
        return None

    def _link(self, ref: sqlite3.Row) -> Target:
        java = self.files[ref["file_id"]]["language"] == JAVA
        return self._link_java(ref) if java else self._link_script(ref)

    def _java_type(self, name: str, file_id: int, within: Optional[int]) -> Target:
        """Resolves a type name as javac would: enclosing types, imports, the package, then java.lang."""
        scope = within
        while scope is not None:
            qualified = self.symbols[scope]["qualified"]
            if self.symbols[scope]["name"] == name:
                return scope
            if f"{qualified}.{name}" in self.java_types:
                return self.java_types[f"{qualified}.{name}"]
            scope = self._enclosing_type(self.symbols[scope]["parent_id"])
        if "." in name:
            if name in self.java_types:
                return self.java_types[name]
            first, rest = name.split(".", 1)
            outer = self._java_type(first, file_id, within) if first[:1].isupper() else None
            if isinstance(outer, int):
                return self.java_types.get(f"{self.symbols[outer]['qualified']}.{rest}")
            if isinstance(outer, str):
                return f"{outer}.{rest}"
            return name if first[:1].islower() else None   # Written out in full: an outside type
        single = self.java_single[file_id].get(name)
        if single:
            return self.java_types.get(single, single)
        package = self.files[file_id]["package"]
        for prefix in (package, *self.java_wild[file_id]):
            qualified = f"{prefix}.{name}" if prefix else name
            if qualified in self.java_types:
                return self.java_types[qualified]
        if name in _JAVA_LANG:
            return f"java.lang.{name}"
        # Not declared here: with a single outside "import x.y.*", that's the only place left it can come from
        outside = [p for p in self.java_wild[file_id] if p not in self.java_packages]
        return f"{outside[0]}.{name}" if len(outside) == 1 else None

    def _link_java(self, ref: sqlite3.Row) -> Target:
        file_id, name, kind = ref["file_id"], ref["name"], ref["kind"]
        within = self._enclosing_type(ref["from_symbol"])
        if kind == "new":
            target = self._java_type(name, file_id, within)
            if isinstance(target, int):   # The constructor taking this many arguments, when it's declared
                simple = self.symbols[target]["name"]
                return self._method(target, simple, ref["args"], ("constructor",), set()) or target
            return target
        if kind != "call":
            return self._java_type(name, file_id, within)

        receiver, args = ref["receiver"], ref["args"]
        if receiver in ("this", "super"):
            scope = within
            while scope is not None:   # The class, what it extends, then the classes it's nested in
                start = [scope] if receiver == "this" else self.supers.get(scope, [])
                for type_id in start:
                    found = self._method(type_id, name, args)
                    if found is not None:
                        return found
                if receiver == "super":
                    break
                scope = self._enclosing_type(self.symbols[scope]["parent_id"])
            if receiver == "this":   # A statically imported method
                owners = [self.java_static[file_id][name]] if name in self.java_static[file_id] else []
                for owner in owners + self.java_static_wild[file_id]:
                    if owner in self.java_types:
                        found = self._method(self.java_types[owner], name, args)
                        if found is not None:
                            return found
                    elif owner in owners:
                        return f"{owner}#{name}"
            outside = self.external_supers.get(within, []) if within is not None else []
            return f"{outside[0]}#{name}" if len(outside) == 1 and not self.supers.get(within) else None
        if not receiver:
            return None
        owner = self._java_type(receiver, file_id, within)
        if isinstance(owner, int):
            return self._method(owner, name, args)
        return f"{owner}#{name}" if owner else None

    def _binding(self, file_id: int, name: str) -> Tuple[Target, Optional[int]]:
        """What a name stands for in a JS/TS file: (a symbol or external name, or else the module file it is)."""
        if name in self.bindings[file_id]:
            target_file, package, imported = self.bindings[file_id][name]
            if package:
                return (package if imported in ("*", "default") else f"{package}#{imported}"), None
            if target_file is None:
                return None, None
            if imported in ("*", "default"):
                default = self.default.get(target_file)
                return (default if imported == "default" else None), target_file
            return self.top[target_file].get(imported), None
        return self.top[file_id].get(name), None

    def _link_script(self, ref: sqlite3.Row) -> Target:
        file_id, name, receiver, args = ref["file_id"], ref["name"], ref["receiver"], ref["args"]
        if not receiver:
            target, module = self._binding(file_id, name)
            if target is None and module is not None:
                return self.default.get(module)   # Calling what require() returned: the module's export
            if isinstance(target, int) and ref["kind"] == "new":
                return self._method(target, "constructor", args, ("constructor",), set()) or target
            return target
        if receiver in ("this", "super"):
            within = self._enclosing_type(ref["from_symbol"])
            if within is None:   # A method of an object literal: its siblings
                owner = self.symbols.get(ref["from_symbol"] or -1)
                within = owner["parent_id"] if owner is not None else None
            if within is None:
                return None
            start = [within] if receiver == "this" else self.supers.get(within, [])
            return next((found for t in start if (found := self._method(t, name, args)) is not None), None)

        base, *rest = receiver.split(".")
        if base == "this":
            return None
        target, module = self._binding(file_id, base)
        if isinstance(target, str):
            return f"{target}{'.' if '#' in target else '#'}{'.'.join([*rest, name])}"
        if rest:
            return None
        found = self._method(target, name, args) if isinstance(target, int) else None   # A member of a class or object
        if found is None and module is not None:   # A namespace or required module: one of its exports
            found = self.top[module].get(name)
            if found is None and module in self.default:
                found = self._method(self.default[module], name, args)
        return found
        return None
