"""
The Patterns view (ADR-013): what's usual in a codebase, counted from the index. Idioms per type,
how types are obtained, calls that go together, entry points and layers, hotspots, naming and test
conventions, how errors are raised, and the Angular and React structure. Every count is over
linked references, and every item carries the usages it was counted from.
"""
import posixpath
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.code.models import Usage
from src.code.parser import TYPE_KINDS
from src.code.store import CodeStore

PATTERN_MIN = 3          # Call sites a type needs before its idioms are shown
PAIR_SUPPORT = 3         # Methods a pair must appear in
PAIR_CONFIDENCE = 0.8    # Share of the methods calling the first that also call the second
NAMING_SHARE = 0.6       # Share of a package's types a suffix must cover
TEST_NAMES = re.compile(r"(Test|Tests|Spec|IT)\.java$|\.(test|spec)\.[jt]sx?$|(^|/)__tests__/")


@dataclass
class Where:
    """One place: a file and line, the symbol it's in."""
    file_id: int
    path: str
    line: int
    enclosing: str


@dataclass
class Member:
    name: str
    calls: int
    examples: List[Where]


@dataclass
class Pair:
    first: str
    second: str
    methods: int                # Idioms: methods where first is called and then second
    examples: List[Where]
    support: int = 0            # Pairs that go together: methods calling both
    confidence: float = 0.0
    of: int = 0                 # Methods calling the first


@dataclass
class Idiom:
    type_id: int
    type_name: str
    qualified: str
    call_sites: int
    members: List[Member]
    pairs: List[Pair]


@dataclass
class Made:
    type_id: int
    type_name: str
    qualified: str
    constructed: int
    injected: int
    factory: int
    examples: List[Where]


@dataclass
class Node:
    symbol: str
    symbol_id: int
    line: int
    children: List["Node"] = field(default_factory=list)


@dataclass
class EntryPoint:
    route: str
    handler: str
    handler_id: Optional[int]
    file_id: int
    path: str
    line: int
    chain: List[Node]


@dataclass
class HotSymbol:
    symbol_id: int
    name: str
    qualified: str
    kind: str
    references: int
    examples: List[Where]


@dataclass
class HotFile:
    file_id: int
    path: str
    references: int


@dataclass
class Naming:
    package: str
    suffix: str
    count: int
    total: int
    examples: List[Where]


@dataclass
class Raised:
    type_name: str
    count: int
    examples: List[Where]


@dataclass
class AngularComponent:
    symbol_id: int
    name: str
    selector: str
    template: str               # The template file's path, or "" when inline
    inputs: List[str]
    outputs: List[str]
    injected: List[str]
    renders: List[str]          # Components its template uses
    file_id: int
    path: str
    line: int


@dataclass
class ReactComponent:
    symbol_id: int
    name: str
    renders: List[str]
    hooks: List[str]
    file_id: int
    path: str
    line: int


@dataclass
class Patterns:
    idioms: List[Idiom]
    made: List[Made]
    pairs: List[Pair]
    entry_points: List[EntryPoint]
    layers: List[str]
    hot_symbols: List[HotSymbol]
    hot_files: List[HotFile]
    naming: List[Naming]
    test_folders: List[str]
    errors: List[Raised]
    angular: List[AngularComponent]
    react: List[ReactComponent]


def _where(row: sqlite3.Row) -> Where:
    return Where(row["file_id"], row["path"], row["line"], row["enclosing"] or "")


def _short(qualified: str) -> str:
    return qualified.rsplit(".", 1)[-1]


class _Miner:
    def __init__(self, store: CodeStore, codebase_id: int):
        self.store, self.conn, self.cid = store, store.conn, codebase_id
        self.symbols = {row["id"]: row for row in self.conn.execute("SELECT * FROM code_symbols WHERE codebase_id = ?", (codebase_id,))}
        self.files = {row["id"]: row for row in self.conn.execute("SELECT * FROM code_files WHERE codebase_id = ?", (codebase_id,))}
        # Linked references with where they are
        self.refs = self.conn.execute(
            "SELECT r.*, f.path, s.qualified AS enclosing FROM code_refs r JOIN code_files f ON f.id = r.file_id "
            "LEFT JOIN code_symbols s ON s.id = r.from_symbol WHERE r.codebase_id = ? AND r.target_id IS NOT NULL "
            "ORDER BY f.path, r.line, r.col", (codebase_id,)).fetchall()
        self.test_files = {fid for fid, f in self.files.items() if TEST_NAMES.search(f["path"])}
        self._owners: Dict[int, Optional[int]] = {}
        self._types: Dict[Tuple[str, str], Optional[int]] = {}

    def owner(self, symbol_id: int) -> Optional[int]:
        if symbol_id in self._owners:
            return self._owners[symbol_id]
        s = self.symbols.get(symbol_id)
        while s is not None and s["kind"] not in TYPE_KINDS:
            s = self.symbols.get(s["parent_id"]) if s["parent_id"] is not None else None
        self._owners[symbol_id] = s["id"] if s is not None else None
        return self._owners[symbol_id]

    # ---- Idioms per type ------------------------------------------------------------------------

    def idioms(self) -> List[Idiom]:
        calls = [r for r in self.refs if r["kind"] == "call" and self.symbols.get(r["target_id"], {"kind": ""})["kind"] in ("method", "function")]
        by_type: Dict[int, List[sqlite3.Row]] = defaultdict(list)
        for r in calls:
            owner = self.owner(r["target_id"])
            if owner is not None and owner != self.owner(r["from_symbol"] or -1):   # Calls from inside the type aren't idioms of using it
                by_type[owner].append(r)
        out = []
        for type_id, rows in by_type.items():
            if len(rows) < PATTERN_MIN:
                continue
            members: Dict[str, List[sqlite3.Row]] = defaultdict(list)
            for r in rows:
                members[self.symbols[r["target_id"]]["name"]].append(r)
            # Ordered pairs within one method
            by_method: Dict[int, List[sqlite3.Row]] = defaultdict(list)
            for r in rows:
                if r["from_symbol"] is not None:
                    by_method[r["from_symbol"]].append(r)
            pairs: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)
            for method_rows in by_method.values():
                names = [self.symbols[r["target_id"]]["name"] for r in sorted(method_rows, key=lambda r: (r["line"], r["col"]))]
                seen: Set[Tuple[str, str]] = set()
                for i, a in enumerate(names):
                    for b in names[i + 1:]:
                        if a != b and (a, b) not in seen:
                            seen.add((a, b))
                            pairs[(a, b)].append(method_rows[0])
            type_row = self.symbols[type_id]
            out.append(Idiom(type_id, type_row["name"], type_row["qualified"], len(rows),
                             sorted([Member(n, len(rs), [_where(r) for r in rs[:10]]) for n, rs in members.items()], key=lambda m: (-m.calls, m.name)),
                             sorted([Pair(a, b, len(rs), [_where(r) for r in rs[:10]]) for (a, b), rs in pairs.items()], key=lambda p: (-p.methods, p.first, p.second))))
        return sorted(out, key=lambda i: (-i.call_sites, i.type_name))

    # ---- How things are made ---------------------------------------------------------------------

    def made(self) -> List[Made]:
        counts: Dict[int, Dict[str, List[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
        for r in self.refs:
            if r["kind"] == "new":
                owner = self.owner(r["target_id"])
                if owner is not None:
                    counts[owner]["constructed"].append(r)
            elif r["kind"] == "call":
                target = self.symbols.get(r["target_id"])
                if target is not None and target["kind"] in ("method", "function") and target["type"]:
                    returned = self._type_named(target["type"].split("<")[0].strip(), target["file_id"])
                    if returned is not None and returned != self.owner(target["id"]) or (returned is not None and target["kind"] == "function"):
                        counts[returned]["factory"].append(r)
        # Injection: fields and constructor parameters of the type with no construction of their own
        constructed_lines = {(r["file_id"], r["line"]) for r in self.refs if r["kind"] == "new"}
        for s in self.symbols.values():
            if s["kind"] == "field" and s["type"]:
                type_id = self._type_named(s["type"].split("<")[0].strip(), s["file_id"])
                if type_id is not None and (s["file_id"], s["line"]) not in constructed_lines:
                    counts[type_id]["injected"].append(self._row_for_symbol(s))
        out = []
        for type_id, groups in counts.items():
            t = self.symbols[type_id]
            examples = [_where(r) for group in ("injected", "constructed", "factory") for r in groups.get(group, [])[:5]]
            out.append(Made(type_id, t["name"], t["qualified"], len(groups.get("constructed", [])), len(groups.get("injected", [])),
                            len(groups.get("factory", [])), examples))
        return sorted(out, key=lambda m: (-(m.constructed + m.injected + m.factory), m.type_name))

    def _type_named(self, name: str, file_id: int) -> Optional[int]:
        """A type of the codebase by its simple or qualified name, as seen from a file (imports first, then same package)."""
        if not name or name[:1].islower():
            return None
        key = (name, self.files[file_id]["package"] if self.files[file_id]["language"] == "java" else str(file_id))
        if key in self._types:
            return self._types[key]
        linker = self.store.linker(self.cid)
        found = linker._java_type(name, file_id, None) if self.files[file_id]["language"] == "java" else linker._binding(file_id, name)[0]
        self._types[key] = found if isinstance(found, int) and self.symbols.get(found, {"kind": ""})["kind"] in TYPE_KINDS else None
        return self._types[key]

    def _row_for_symbol(self, s: sqlite3.Row) -> dict:
        parent = self.symbols.get(s["parent_id"]) if s["parent_id"] is not None else None
        return {"file_id": s["file_id"], "path": self.files[s["file_id"]]["path"], "line": s["line"], "enclosing": parent["qualified"] if parent else s["qualified"]}

    # ---- Pairs that go together -------------------------------------------------------------------

    def pairs(self) -> List[Pair]:
        by_method: Dict[int, Dict[str, sqlite3.Row]] = defaultdict(dict)
        for r in self.refs:
            if r["kind"] == "call" and r["from_symbol"] is not None:
                target = self.symbols.get(r["target_id"])
                if target is not None and target["kind"] in ("method", "function"):
                    by_method[r["from_symbol"]].setdefault(target["name"], r)   # By member name: overloads and siblings count as one
        with_name: Dict[str, Set[int]] = defaultdict(set)
        for method, names in by_method.items():
            for name in names:
                with_name[name].add(method)
        out = []
        for a, methods_a in with_name.items():
            for b, methods_b in with_name.items():
                if a >= b:
                    continue
                both = methods_a & methods_b
                if len(both) < PAIR_SUPPORT:
                    continue
                forward, backward = len(both) / len(methods_a), len(both) / len(methods_b)
                if max(forward, backward) < PAIR_CONFIDENCE:
                    continue
                first, second, confidence = (a, b, forward) if forward >= backward else (b, a, backward)
                out.append(Pair(first, second, len(both), [_where(by_method[m][first]) for m in sorted(both)[:10]], len(both), round(confidence, 2),
                                len(methods_a) if first == a else len(methods_b)))
        return sorted(out, key=lambda p: (-p.support, -p.confidence, p.first, p.second))

    # ---- Entry points and layers -------------------------------------------------------------------

    def entry_points(self) -> List[EntryPoint]:
        rows = self.conn.execute(
            "SELECT e.*, f.path FROM code_endpoints e JOIN code_files f ON f.id = e.file_id WHERE e.codebase_id = ? AND e.side = 'server' "
            "ORDER BY f.path, e.line", (self.cid,)).fetchall()
        callees: Dict[int, List[sqlite3.Row]] = defaultdict(list)
        for r in self.refs:
            if r["kind"] == "call" and r["from_symbol"] is not None and self.symbols.get(r["target_id"], {"kind": ""})["kind"] in ("method", "function"):
                callees[r["from_symbol"]].append(r)

        def chain(symbol_id: int, depth: int, seen: Set[int]) -> List[Node]:
            nodes = []
            for r in callees.get(symbol_id, []):
                target = r["target_id"]
                if target in seen:
                    continue
                node = Node(self.symbols[target]["qualified"], target, r["line"])
                if depth > 1:
                    node.children = chain(target, depth - 1, seen | {target})
                nodes.append(node)
            return nodes
        out = []
        for e in rows:
            handler = self.symbols.get(e["symbol_id"]) if e["symbol_id"] is not None else None
            out.append(EntryPoint(f"{e['method']} {e['path']}", handler["qualified"] if handler else "", e["symbol_id"], e["file_id"], e["path"], e["line"],
                                  chain(e["symbol_id"], 3, {e["symbol_id"]}) if handler else []))
        return out

    def layers(self) -> List[str]:
        """Packages from the most depending to the most depended on."""
        out_deps: Dict[str, Set[str]] = defaultdict(set)
        in_deps: Dict[str, Set[str]] = defaultdict(set)
        packages = {f["package"] for f in self.files.values() if f["language"] == "java"}
        for r in self.refs:
            source = self.files[r["file_id"]]["package"]
            target = self.symbols.get(r["target_id"])
            if target is None:
                continue
            dest = self.files[target["file_id"]]["package"]
            if source != dest and source in packages and dest in packages:
                out_deps[source].add(dest)
                in_deps[dest].add(source)
        return sorted(packages, key=lambda p: (-(len(out_deps[p]) - len(in_deps[p])), p))

    # ---- Hotspots -----------------------------------------------------------------------------------

    def hotspots(self) -> Tuple[List[HotSymbol], List[HotFile]]:
        by_symbol: Dict[int, List[sqlite3.Row]] = defaultdict(list)
        by_file: Counter = Counter()
        for r in self.refs:
            by_symbol[r["target_id"]].append(r)
            target = self.symbols.get(r["target_id"])
            if target is not None and target["file_id"] != r["file_id"]:
                by_file[target["file_id"]] += 1
        counted = sorted(((len(rows), symbol_id) for symbol_id, rows in by_symbol.items()
                          if (s := self.symbols.get(symbol_id)) is not None and s["kind"] not in TYPE_KINDS),
                         key=lambda pair: (-pair[0], self.symbols[pair[1]]["qualified"]))[:20]
        symbols = [HotSymbol(sid, self.symbols[sid]["name"], self.symbols[sid]["qualified"], self.symbols[sid]["kind"], n,
                             [_where(r) for r in by_symbol[sid][:10]]) for n, sid in counted]
        files = [HotFile(fid, self.files[fid]["path"], n) for fid, n in by_file.most_common(20)]
        return symbols, files

    # ---- Conventions --------------------------------------------------------------------------------

    def naming(self) -> List[Naming]:
        by_package: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for s in self.symbols.values():
            if s["kind"] in TYPE_KINDS and s["parent_id"] is None and s["file_id"] not in self.test_files:
                by_package[self.files[s["file_id"]]["package"]].append(s)
        out = []
        for package, types in by_package.items():
            if len(types) < 2:
                continue
            suffixes: Counter = Counter()
            for s in types:
                words = re.findall(r"[A-Z][a-z0-9]+|[A-Z]+(?![a-z])", s["name"])
                for n in range(1, len(words) + 1):
                    suffixes["".join(words[-n:])] += 1
            best = max(suffixes.items(), key=lambda kv: (kv[1], len(kv[0])), default=None)
            if best and best[1] / len(types) >= NAMING_SHARE:
                suffix, count = best
                matching = [s for s in types if s["name"].endswith(suffix)]
                out.append(Naming(package, suffix, count, len(types), [_where(self._row_for_symbol(s)) for s in matching[:10]]))
        return sorted(out, key=lambda n: n.package)

    def test_folders(self) -> List[str]:
        totals: Counter = Counter()
        tests: Counter = Counter()
        for fid, f in self.files.items():
            folder = posixpath.dirname(f["path"])
            while True:
                totals[folder] += 1
                if fid in self.test_files:
                    tests[folder] += 1
                if not folder:
                    break
                folder = posixpath.dirname(folder)
        qualifying = {folder for folder in totals if folder and tests[folder] >= 0.8 * totals[folder]}
        return sorted(f for f in qualifying if posixpath.dirname(f) not in qualifying)

    def errors(self) -> List[Raised]:
        raised: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for r in self.conn.execute(
                "SELECT r.*, f.path, s.qualified AS enclosing FROM code_refs r JOIN code_files f ON f.id = r.file_id "
                "LEFT JOIN code_symbols s ON s.id = r.from_symbol WHERE r.codebase_id = ? AND r.kind = 'new' AND r.shape LIKE '%W%' "
                "ORDER BY f.path, r.line", (self.cid,)):
            raised[r["name"]].append(r)
        return sorted([Raised(name, len(rows), [_where(r) for r in rows[:10]]) for name, rows in raised.items()], key=lambda e: (-e.count, e.type_name))

    # ---- Framework views ----------------------------------------------------------------------------

    def angular(self) -> List[AngularComponent]:
        rows = self.conn.execute("SELECT c.*, s.name, s.file_id, s.line FROM code_components c JOIN code_symbols s ON s.id = c.symbol_id "
                                 "WHERE c.codebase_id = ? ORDER BY s.name", (self.cid,)).fetchall()
        decorated: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        for r in self.conn.execute("SELECT r.name AS decorator, s.name AS member, s.parent_id FROM code_refs r JOIN code_symbols s ON s.id = r.from_symbol "
                                   "WHERE r.codebase_id = ? AND r.kind = 'annotation' AND s.kind = 'field' AND r.name IN ('Input', 'Output')", (self.cid,)):
            decorated[(r["parent_id"], r["decorator"])].append(r["member"])
        out = []
        for c in rows:
            injected = [s["type"].split("<")[0] for s in self.symbols.values()
                        if s["parent_id"] == c["symbol_id"] and s["kind"] == "field" and s["type"] and self._type_named(s["type"].split("<")[0], s["file_id"]) is not None
                        and s["line"] not in {m["line"] for m in self.symbols.values() if m["parent_id"] == c["symbol_id"] and m["kind"] == "field" and m["name"] in decorated.get((c["symbol_id"], "Input"), []) + decorated.get((c["symbol_id"], "Output"), [])}]
            renders = sorted({self.symbols[r["target_id"]]["name"] for r in self.refs
                              if r["kind"] == "jsx" and (r["from_symbol"] == c["symbol_id"] or (c["template_file"] and r["file_id"] == c["template_file"]))})
            out.append(AngularComponent(c["symbol_id"], c["name"], c["selector"], self.files[c["template_file"]]["path"] if c["template_file"] else "",
                                        sorted(decorated.get((c["symbol_id"], "Input"), [])), sorted(decorated.get((c["symbol_id"], "Output"), [])),
                                        sorted(set(injected)), renders, c["file_id"], self.files[c["file_id"]]["path"], c["line"]))
        return out

    def react(self) -> List[ReactComponent]:
        renders: Dict[int, Set[str]] = defaultdict(set)
        hooks: Dict[int, Set[str]] = defaultdict(set)
        for r in self.refs:
            if r["from_symbol"] is None:
                continue
            if r["kind"] == "jsx":
                renders[r["from_symbol"]].add(self.symbols[r["target_id"]]["name"])
            elif r["kind"] == "call" and re.match(r"use[A-Z]", r["name"]):
                hooks[r["from_symbol"]].add(r["name"])
        for r in self.conn.execute("SELECT from_symbol, name FROM code_refs WHERE codebase_id = ? AND kind = 'call' AND target IS NOT NULL "
                                   "AND from_symbol IS NOT NULL AND name GLOB 'use[A-Z]*'", (self.cid,)):
            hooks[r["from_symbol"]].add(r["name"])   # React's own hooks are an outside API
        rendered = {r["target_id"] for r in self.refs if r["kind"] == "jsx" and self.files[r["file_id"]]["language"] != "html"}
        components = {sid for sid in set(renders) | set(hooks) | rendered if self.symbols[sid]["kind"] in ("function", "class", "variable")
                      and self.symbols[sid]["name"][:1].isupper() and self.files[self.symbols[sid]["file_id"]]["language"] in ("javascript", "typescript")
                      and (sid in renders or sid in rendered)}
        out = []
        for sid in components:
            s = self.symbols[sid]
            out.append(ReactComponent(sid, s["name"], sorted(renders[sid]), sorted(hooks[sid]), s["file_id"], self.files[s["file_id"]]["path"], s["line"]))
        return sorted(out, key=lambda c: c.name)


_cache: Dict[Tuple[int, str], Patterns] = {}


def patterns_for(store: CodeStore, codebase_id: int) -> Patterns:
    """The codebase's patterns, cached until its index changes."""
    stamp = store.conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(LENGTH(sha256)), 0) FROM code_files WHERE codebase_id = ?",
                               (codebase_id,)).fetchone()
    symbols = store.conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM code_symbols WHERE codebase_id = ?", (codebase_id,)).fetchone()
    key = (codebase_id, f"{tuple(stamp)}{tuple(symbols)}{store.conn.execute('SELECT COALESCE(MAX(id), 0) FROM code_refs WHERE codebase_id = ?', (codebase_id,)).fetchone()[0]}")
    if key in _cache:
        return _cache[key]
    for old in [k for k in _cache if k[0] == codebase_id]:
        del _cache[old]
    miner = _Miner(store, codebase_id)
    hot_symbols, hot_files = miner.hotspots()
    result = Patterns(miner.idioms(), miner.made(), miner.pairs(), miner.entry_points(), miner.layers(), hot_symbols, hot_files,
                      miner.naming(), miner.test_folders(), miner.errors(), miner.angular(), miner.react())
    _cache[key] = result
    return result
