"""
The change-impact view (ADR-018): everything that reaches a symbol through calls, as a closure
over callers with its depth and certainty, grouped by layer, with the HTTP routes and the tests
among them. Edges come from the index's usages, so by-name links are followed only when asked.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from src.code.models import BY_NAME, RESOLVED, SUPERTYPE, Symbol, Usage
from src.code.parser import JAVA
from src.code.patterns import TEST_NAMES
from src.code.store import CodeStore

MAX_DEPTH = 8
MAX_NODES = 400
_STRENGTH = {RESOLVED: 0, SUPERTYPE: 1, BY_NAME: 2}


@dataclass
class Node:
    symbol_id: int
    qualified: str
    kind: str
    file_id: int
    path: str
    line: int
    depth: int
    certainty: str              # The weakest edge on the shortest path from the symbol
    via: int                    # The symbol it reaches (the next step down)
    via_line: int


@dataclass
class Layer:
    layer: str
    nodes: List[Node]


@dataclass
class Route:
    route: str
    handler: str
    handler_id: int
    depth: int


@dataclass
class TestFile:
    file_id: int
    path: str
    symbols: List[str]


@dataclass
class Impact:
    symbol: Symbol
    nodes: List[Node]
    layers: List[Layer]
    routes: List[Route]
    tests: List[TestFile]
    truncated: bool
    by_name_included: bool


def package_layers(store: CodeStore, codebase_id: int) -> List[str]:
    """Java packages from the most depending to the most depended on, from one query over the linked references."""
    out_deps: Dict[str, Set[str]] = defaultdict(set)
    in_deps: Dict[str, Set[str]] = defaultdict(set)
    packages = {row[0] for row in store.conn.execute("SELECT DISTINCT package FROM code_files WHERE codebase_id = ? AND language = 'java'", (codebase_id,))}
    for source, dest in store.conn.execute(
            "SELECT DISTINCT f1.package, f2.package FROM code_refs r JOIN code_files f1 ON f1.id = r.file_id "
            "JOIN code_symbols s ON s.id = r.target_id JOIN code_files f2 ON f2.id = s.file_id "
            "WHERE r.codebase_id = ? AND f1.language = 'java' AND f2.language = 'java' AND f1.package != f2.package", (codebase_id,)):
        out_deps[source].add(dest)
        in_deps[dest].add(source)
    return sorted(packages, key=lambda p: (-(len(out_deps[p]) - len(in_deps[p])), p))


def _edges(store: CodeStore, symbol: Symbol, by_name: bool) -> List[Usage]:
    """The usages that are edges here: linked ones (and through supertypes) always, by-name ones when asked."""
    if by_name:
        usages = store.usages(symbol)
        if symbol.is_type:
            for member in store.members(symbol.id):
                usages += store.usages(member)
        return [u for u in usages if u.from_symbol is not None]
    ids = [symbol.id] + ([m.id for m in store.members(symbol.id)] if symbol.is_type else [])
    marks = ", ".join("?" * len(ids))
    usages = store._usages(f"r.target_id IN ({marks}) AND r.from_symbol IS NOT NULL", ids, limit=5000)
    overridden = [s.id for s in store.hierarchy(symbol).overrides] if symbol.kind == "method" else []
    if overridden:
        marks = ", ".join("?" * len(overridden))
        usages += store._usages(f"r.target_id IN ({marks}) AND r.from_symbol IS NOT NULL", overridden, SUPERTYPE, limit=5000)
    return usages


def impact_of(store: CodeStore, symbol: Symbol, by_name: bool = False, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> Impact:
    nodes: Dict[int, Node] = {}
    queue: deque = deque([(symbol, 0, RESOLVED)])
    seen: Set[int] = {symbol.id}
    truncated = False
    while queue:
        current, depth, weakest = queue.popleft()
        if depth >= max_depth:
            truncated = True
            continue
        for usage in _edges(store, current, by_name):
            caller_id = usage.from_symbol
            if caller_id in seen:
                continue
            if len(nodes) >= max_nodes:
                truncated = True
                break
            caller = store.symbol(caller_id)
            if caller is None:
                continue
            seen.add(caller_id)
            certainty = max((weakest, usage.certainty), key=lambda c: _STRENGTH[c])
            nodes[caller_id] = Node(caller_id, caller.qualified, caller.kind, caller.file_id, caller.path, caller.line, depth + 1,
                                    certainty, current.id, usage.line)
            queue.append((caller, depth + 1, certainty))
        if truncated and len(nodes) >= max_nodes:
            break
    ordered = sorted(nodes.values(), key=lambda n: (n.depth, n.path, n.line))

    # Layers: Java packages in dependency order, else top folders
    conn = store.conn
    files = {row["id"]: row for row in conn.execute("SELECT id, path, language, package FROM code_files WHERE codebase_id = ?", (symbol.codebase_id,))}
    order = package_layers(store, symbol.codebase_id) if any(f["language"] == JAVA for f in files.values()) else []
    rank = {package: i for i, package in enumerate(order)}

    def layer_of(node: Node) -> str:
        f = files.get(node.file_id)
        if f is None:
            return ""
        return f["package"] if f["language"] == JAVA else (f["path"].split("/")[0] if "/" in f["path"] else "")
    grouped: Dict[str, List[Node]] = defaultdict(list)
    for node in ordered:
        grouped[layer_of(node)].append(node)
    layers = [Layer(name, items) for name, items in sorted(grouped.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))]

    handlers = {row["symbol_id"]: (f"{row['method']} {row['path']}", row["symbol_id"]) for row in conn.execute(
        "SELECT method, path, symbol_id FROM code_endpoints WHERE codebase_id = ? AND side = 'server' AND symbol_id IS NOT NULL", (symbol.codebase_id,))}
    routes = [Route(handlers[n.symbol_id][0], n.qualified, n.symbol_id, n.depth) for n in ordered if n.symbol_id in handlers]
    if symbol.id in handlers:
        routes.insert(0, Route(handlers[symbol.id][0], symbol.qualified, symbol.id, 0))
    by_test: Dict[int, List[str]] = defaultdict(list)
    for n in ordered:
        if TEST_NAMES.search(n.path):
            by_test[n.file_id].append(n.qualified)
    tests = [TestFile(fid, files[fid]["path"], names) for fid, names in sorted(by_test.items(), key=lambda kv: files[kv[0]]["path"])]
    return Impact(symbol, ordered, layers, routes, tests, truncated, by_name)
