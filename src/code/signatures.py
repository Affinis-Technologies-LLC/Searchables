"""
Signature-aware search (ADR-019): symbols by kind, name, declared or return type, parameter count
and types, and owner, over the types the index stores. "Methods taking a User and returning
Optional" is a query, not a grep.
"""
import re
from typing import List, Optional

from src.code.models import Symbol
from src.code.store import CodeStore

LIMIT = 300


def _base(type_text: str) -> str:
    """"Optional" for "Optional<Order>", "List" for "java.util.List<User>", "User" for "User[]"."""
    text = type_text.strip().split("<")[0].rstrip("[] ")
    return text.rsplit(".", 1)[-1]


def parameter_types(signature: str) -> List[str]:
    """The parameter types written in a signature: Java "(Order order, boolean flush)", TS "(id: number, o: Order)"."""
    start = signature.find("(")
    if start < 0:
        return []
    depth, end = 0, -1
    for i in range(start, len(signature)):
        if signature[i] == "(":
            depth += 1
        elif signature[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    inside = signature[start + 1:end] if end > 0 else signature[start + 1:]
    parts, depth, current = [], 0, ""
    for c in inside:
        if c in "<([{":
            depth += 1
        elif c in ">)]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += c
    if current.strip():
        parts.append(current)
    types = []
    for part in parts:
        part = re.sub(r"@\w+(\([^)]*\))?\s*", "", part).strip()
        part = re.sub(r"\b(final|private|public|protected|readonly)\s+", "", part)
        if ":" in part:                      # TypeScript: name: Type
            types.append(_base(part.split(":", 1)[1].split("=")[0]))
        else:                                # Java: Type name
            tokens = part.replace("...", "[]").split()
            types.append(_base(tokens[-2]) if len(tokens) >= 2 else _base(tokens[0]) if tokens else "")
    return types


def search_signatures(store: CodeStore, codebase_id: int, kind: str = "", name: str = "", returns: str = "",
                      param: str = "", params: Optional[int] = None, owner: str = "", limit: int = LIMIT) -> List[Symbol]:
    where = ["s.codebase_id = ?"]
    values: list = [codebase_id]
    if kind:
        where.append("s.kind = ?")
        values.append(kind)
    if name:
        where.append("s.name LIKE ? ESCAPE '\\'")
        values.append("%" + name.replace("%", "\\%").replace("_", "\\_") + "%")
    if params is not None:
        where.append("s.params = ?")
        values.append(params)
    if returns:
        where.append("s.type != ''")
    rows = store.conn.execute(
        f"SELECT s.*, f.path, f.language FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE {' AND '.join(where)} "
        f"ORDER BY f.path, s.line", values).fetchall()
    found = []
    for row in rows:
        if returns and _base(row["type"]).lower() != returns.lower():
            continue
        if param and param.lower() not in [t.lower() for t in parameter_types(row["signature"])]:
            continue
        if owner:
            parent = store.conn.execute("SELECT name FROM code_symbols WHERE id = ?", (row["parent_id"],)).fetchone() if row["parent_id"] else None
            if parent is None or parent["name"].lower() != owner.lower():
                continue
        found.append(store.symbol(row["id"]))
        if len(found) >= limit:
            break
    return found
