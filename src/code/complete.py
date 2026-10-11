"""
Completion from the index (ADR-012): after a receiver, the members of its resolved type with the
number of examples each has; otherwise what's in scope, then the file's imports, then symbols of the
codebase that could be imported. Never words from the buffer, never anything the index doesn't know.
"""
import posixpath
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src.code.context import Context, _enclosing_type_index
from src.code.parser import JAVA, TYPE_KINDS
from src.code.store import CodeStore

LIMIT = 60


@dataclass
class Item:
    name: str
    kind: str                   # method, field, function, variable, class, …; "api" for an outside API's member seen used
    params: int
    signature: str
    type: str
    examples: int               # Call sites in the codebase
    detail: str                 # Where it comes from
    insert_import: Optional[str] = None   # An import to add when chosen: a Java qualified name, or a module path
    symbol_id: Optional[int] = None


def _matches(name: str, partial: str) -> bool:
    return name.lower().startswith(partial.lower())


def _examples(store: CodeStore, counts: Dict[int, int], symbol_id: int) -> int:
    if symbol_id not in counts:
        counts[symbol_id] = store.conn.execute(
            "SELECT COUNT(*) FROM code_refs WHERE target_id = ? AND kind IN ('call', 'new')", (symbol_id,)).fetchone()[0]
    return counts[symbol_id]


def _member_items(store: CodeStore, linker, type_id: int, partial: str, counts: Dict[int, int],
                  seen: Optional[Set[int]] = None, depth: int = 0) -> List[Item]:
    seen = seen if seen is not None else set()
    if type_id in seen:
        return []
    seen.add(type_id)
    items = []
    owner = linker.symbols[type_id]["qualified"].rsplit(".", 1)[-1]
    for name, members in linker.members.get(type_id, {}).items():
        if not _matches(name, partial):
            continue
        for member in members:
            if member["kind"] in ("method", "function", "field", "variable"):
                items.append(Item(name, member["kind"], member["params"], member["signature"], member["type"],
                                  _examples(store, counts, member["id"]), owner + (" (inherited)" if depth else ""),
                                  symbol_id=member["id"]))
    for parent in linker.supers.get(type_id, []):
        items += _member_items(store, linker, parent, partial, counts, seen, depth + 1)
    return items


def _module_path(from_path: str, to_path: str) -> str:
    """'../api/customers' for an import of to_path from from_path (no extension; './' when beside)."""
    relative = posixpath.relpath(posixpath.splitext(to_path)[0], posixpath.dirname(from_path))
    if relative.endswith("/index"):
        relative = relative[:-6]
    return relative if relative.startswith(".") else "./" + relative


def complete_at(store: CodeStore, context: Context, limit: int = LIMIT) -> List[Item]:
    linker = store.linker(context.codebase_id)
    expression, partial = context.expression, context.expression.partial
    counts: Dict[int, int] = {}
    java = context.language == JAVA
    items: List[Item] = []

    if expression.kind == "call" and expression.receiver:
        type_ref = context.receiver_type
        if type_ref is None:
            return []
        if type_ref.id is not None:
            items = _member_items(store, linker, type_ref.id, partial, counts)
        else:
            # An outside API: the members the codebase has been seen to use on it
            prefix = type_ref.qualified + ("." if "#" in type_ref.qualified else "#")
            for row in store.conn.execute(
                    "SELECT target, COUNT(*) AS n FROM code_refs WHERE codebase_id = ? AND target LIKE ? ESCAPE '\\' "
                    "AND kind = 'call' GROUP BY target ORDER BY n DESC", (context.codebase_id, prefix.replace("_", "\\_") + "%")):
                name = row["target"][len(prefix):]
                if "." not in name and "#" not in name and _matches(name, partial):
                    items.append(Item(name, "api", -1, "", "", row["n"], type_ref.qualified.replace("#", ".").lstrip(".")))
        return sorted(items, key=lambda i: (i.name.lower(), i.params))[:limit]

    if expression.kind != "call" or expression.receiver:
        return []
    seen: Set[str] = set()

    def add(item: Item) -> None:
        key = f"{item.name}/{item.params}"
        if key not in seen and _matches(item.name, partial):
            seen.add(key)
            items.append(item)

    # In scope: the enclosing method's parameters and locals, then the enclosing type's members
    for name, declared in sorted(context.locals.items()):
        add(Item(name, "variable", -1, f"{declared} {name}" if declared and not declared.startswith(("N:", "T:")) else name,
                 declared[2:] if declared.startswith("T:") else declared if not declared.startswith("N:") else "", 0, "in scope"))
    parsed = context.parsed
    type_index = _enclosing_type_index(parsed, context.enclosing_index)
    if type_index is not None:
        for symbol in parsed.symbols:
            if symbol.parent == type_index and symbol.kind in ("method", "field", "function", "variable"):
                add(Item(symbol.name, symbol.kind, symbol.params, symbol.signature, symbol.type, 0, parsed.symbols[type_index].name))
        stored_type = context.enclosing.type_id if context.enclosing else None
        if stored_type is not None:
            for parent in linker.supers.get(stored_type, []):
                for item in _member_items(store, linker, parent, partial, counts):
                    add(item)
    # The file's own top-level symbols and what it imports
    for symbol in parsed.symbols:
        if symbol.parent is None and symbol.kind not in ("constructor",):
            add(Item(symbol.name, symbol.kind, symbol.params, symbol.signature, symbol.type,
                     0, "this file"))
    if java:
        for name, qualified in linker.java_single.get(context.file_id, {}).items():
            symbol_id = linker.java_types.get(qualified)
            symbol = linker.symbols.get(symbol_id) if symbol_id is not None else None
            add(Item(name, symbol["kind"] if symbol else "class", -1, symbol["signature"] if symbol else qualified, "",
                     _examples(store, counts, symbol_id) if symbol_id else 0, "imported", symbol_id=symbol_id))
    else:
        for name, (file_id, external, imported) in linker.bindings.get(context.file_id, {}).items():
            symbol_id = linker.top.get(file_id, {}).get(imported) if file_id is not None else None
            if imported == "default" and file_id is not None:
                symbol_id = linker.default.get(file_id)
            symbol = linker.symbols.get(symbol_id) if symbol_id is not None else None
            add(Item(name, symbol["kind"] if symbol else "import", symbol["params"] if symbol else -1,
                     symbol["signature"] if symbol else name, symbol["type"] if symbol else "",
                     _examples(store, counts, symbol_id) if symbol_id else 0, external or "imported", symbol_id=symbol_id))
    # Importable: exported top-level symbols of the codebase, by prefix
    if partial:
        for symbol in store.search_symbols(context.codebase_id, partial, limit=200):
            if symbol.file_id == context.file_id or symbol.parent_id is not None or not symbol.name.lower().startswith(partial.lower()):
                continue
            if java:
                if symbol.kind not in TYPE_KINDS or not symbol.exported:
                    continue
                add(Item(symbol.name, symbol.kind, -1, symbol.signature, "", _examples(store, counts, symbol.id),
                         symbol.qualified.rsplit(".", 1)[0], insert_import=symbol.qualified, symbol_id=symbol.id))
            else:
                if not symbol.exported or symbol.language == "html":
                    continue
                add(Item(symbol.name, symbol.kind, symbol.params, symbol.signature, symbol.type,
                         _examples(store, counts, symbol.id), symbol.path, insert_import=_module_path(context.path, symbol.path),
                         symbol_id=symbol.id))
    return items[:limit]
