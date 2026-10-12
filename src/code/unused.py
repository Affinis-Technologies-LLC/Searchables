"""
Dead and unreachable code (ADR-019): what the index never sees referenced. Methods nothing calls,
routes nothing reaches, exports nothing imports, types nothing refers to; each with its certainty,
so a symbol whose only references are by name is listed apart, never as dead.
"""
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src import config
from src.code.models import Symbol
from src.code.parser import JAVA, TYPE_KINDS
from src.code.patterns import TEST_NAMES
from src.code.store import CodeStore

ENTRY_NAMES = {"main"}
LIFECYCLE = {"toString", "equals", "hashCode", "compareTo", "close", "run", "call", "apply", "accept", "get", "test",
             "ngOnInit", "ngOnDestroy", "ngOnChanges", "ngAfterViewInit", "ngAfterContentInit", "ngDoCheck",
             "componentDidMount", "componentWillUnmount", "componentDidUpdate", "render", "shouldComponentUpdate",
             "getDerivedStateFromProps", "constructor", "init", "destroy", "setUp", "tearDown"}
ENTRY_FILES = re.compile(r"(^|/)(index|main|app|server|bootstrap|polyfills|setupTests|vite\.config|webpack\.config)\.[cm]?[jt]sx?$")


@dataclass
class Unused:
    symbol: Symbol
    certainty: str              # "none": no reference at all; "name": only by-name references
    by_name_references: int = 0


@dataclass
class UnusedRoute:
    route: str
    handler: Optional[Symbol]
    file_id: int
    path: str
    line: int


@dataclass
class Report:
    methods: List[Unused]
    by_name_only: List[Unused]
    routes: List[UnusedRoute]
    exports: List[Unused]
    types: List[Unused]


def unused_in(store: CodeStore, codebase_id: int) -> Report:
    conn = store.conn
    rows = conn.execute("SELECT s.*, f.path, f.language FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE s.codebase_id = ?", (codebase_id,)).fetchall()
    linked: Dict[int, int] = {}
    for target_id, n in conn.execute("SELECT target_id, COUNT(*) FROM code_refs WHERE codebase_id = ? AND target_id IS NOT NULL GROUP BY target_id", (codebase_id,)):
        linked[target_id] = n
    # Links to a type's members from outside the type: a class whose fields only its own methods read is still unused (ADR-025)
    linked_from_outside: Set[int] = set()
    owner_of = {row["id"]: row["parent_id"] for row in rows}
    for target_id, from_symbol in conn.execute(
            "SELECT DISTINCT r.target_id, r.from_symbol FROM code_refs r WHERE r.codebase_id = ? AND r.target_id IS NOT NULL", (codebase_id,)):
        owner = owner_of.get(target_id)
        scope = from_symbol
        while scope is not None and scope != owner:
            scope = owner_of.get(scope)
        if scope is None:
            linked_from_outside.add(target_id)
    by_name: Dict[str, int] = {}
    for name, n in conn.execute("SELECT name, COUNT(*) FROM code_refs WHERE codebase_id = ? AND target_id IS NULL AND target IS NULL GROUP BY name", (codebase_id,)):
        by_name[name] = n
    handlers = {row[0] for row in conn.execute("SELECT symbol_id FROM code_endpoints WHERE codebase_id = ? AND side = 'server' AND symbol_id IS NOT NULL", (codebase_id,))}
    # A framework may call an annotated method (@Bean, @Scheduled, @EventListener, @Test…); marker annotations about the method itself don't count
    annotated = {row[0] for row in conn.execute(
        "SELECT DISTINCT from_symbol FROM code_refs WHERE codebase_id = ? AND kind = 'annotation' AND from_symbol IS NOT NULL "
        "AND name NOT IN ('Override', 'Deprecated', 'SuppressWarnings', 'SafeVarargs', 'FunctionalInterface', 'Nullable', 'NonNull', 'NotNull')",
        (codebase_id,))}
    # An export that's imported counts as used even when the importing file never refers to it
    imported: Set[int] = set()
    linker = store.linker(codebase_id)
    for row in conn.execute("SELECT file_id, target_file, names FROM code_imports WHERE codebase_id = ? AND target_file IS NOT NULL", (codebase_id,)):
        for local, name in json.loads(row["names"] or "{}").items():
            if name == "default":
                sid = linker.default.get(row["target_file"])
            elif name == "*":
                sid = None
                imported |= set(linker.top.get(row["target_file"], {}).values())
            else:
                sid = linker.top.get(row["target_file"], {}).get(name)
            if sid is not None:
                imported.add(sid)
    # A call through a supertype method counts for its overrides
    reached_through_super: Set[int] = set()
    for row in rows:
        if row["kind"] == "method" and linked.get(row["id"]):
            for sub_id in _overriders(store, row["id"]):
                reached_through_super.add(sub_id)

    def used(row) -> bool:
        return bool(linked.get(row["id"])) or row["id"] in reached_through_super or row["id"] in imported

    def entry(row) -> bool:
        if row["id"] in handlers or row["id"] in annotated or TEST_NAMES.search(row["path"]):
            return True
        if row["name"] in ENTRY_NAMES or row["name"] in LIFECYCLE or row["kind"] == "constructor":
            return True
        if row["language"] != JAVA and ENTRY_FILES.search(row["path"]) and row["parent_id"] is None:
            return True
        if config.CODE_LIBRARY_PUBLIC and row["language"] == JAVA and row["exported"]:
            return True
        return False

    def symbol_of(row) -> Symbol:
        return store.symbol(row["id"])

    methods, by_name_only, exports, types = [], [], [], []
    for row in rows:
        if row["kind"] in ("method", "function"):
            if used(row) or entry(row):
                continue
            n = by_name.get(row["name"], 0)
            (by_name_only if n else methods).append(Unused(symbol_of(row), "name" if n else "none", n))
        elif row["kind"] in TYPE_KINDS and row["parent_id"] is None:
            if used(row) or TEST_NAMES.search(row["path"]) or row["id"] in annotated:
                continue
            members_used = any(m["id"] in linked_from_outside or m["id"] in reached_through_super for m in rows if m["parent_id"] == row["id"])
            if members_used:
                continue
            n = by_name.get(row["name"], 0)
            types.append(Unused(symbol_of(row), "name" if n else "none", n))
    for row in rows:
        if row["language"] != JAVA and row["exported"] and row["parent_id"] is None and row["id"] not in imported and not linked.get(row["id"]) \
                and not ENTRY_FILES.search(row["path"]) and not TEST_NAMES.search(row["path"]) and row["kind"] != "constructor":
            exports.append(Unused(symbol_of(row), "name" if by_name.get(row["name"]) else "none", by_name.get(row["name"], 0)))
    served, _ = store.endpoints(codebase_id)
    routes = [UnusedRoute(f"{e.method} {e.path}", store.symbol(e.symbol_id) if e.symbol_id else None, e.file_id, e.file_path, e.line)
              for e, calls in served if not calls]
    key = lambda u: (u.symbol.path, u.symbol.line)
    return Report(sorted(methods, key=key), sorted(by_name_only, key=key), routes, sorted(exports, key=key), sorted(types, key=key))


def _overriders(store: CodeStore, method_id: int) -> List[int]:
    symbol = store.symbol(method_id)
    if symbol is None or symbol.kind != "method":
        return []
    return [s.id for s in store.hierarchy(symbol).overridden_by]
