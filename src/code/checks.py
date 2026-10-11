"""
Convention checks from mined patterns (ADR-021): a method that breaks what the codebase itself
usually does, with the places that establish the rule. Linting whose rules come from the code.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src.code.models import Symbol
from src.code.parser import TYPE_KINDS
from src.code.patterns import NAMING_SHARE, TEST_NAMES, Where, patterns_for
from src.code.store import CodeStore

NAMING_MIN = 3        # Types that must share a suffix before it's a convention
ERROR_COMMON = 10     # Throws of one exception type that make another thrown once look like a one-off
ACCESSOR = re.compile(r"^(get|is|has|set)[A-Z]|^(size|length|toString|equals|hashCode|name|id|value)$")


@dataclass
class Finding:
    kind: str                   # companion, naming, error, layering
    symbol: Symbol
    file_id: int
    path: str
    line: int
    message: str
    examples: List[Where]
    confidence: float


def checks_for(store: CodeStore, codebase_id: int, file_id: Optional[int] = None) -> List[Finding]:
    patterns = patterns_for(store, codebase_id)
    conn = store.conn
    findings: List[Finding] = []
    symbols = {row["id"]: row for row in conn.execute(
        "SELECT s.*, f.path FROM code_symbols s JOIN code_files f ON f.id = s.file_id WHERE s.codebase_id = ?" + (" AND s.file_id = ?" if file_id else ""),
        (codebase_id, file_id) if file_id else (codebase_id,))}
    # Calls per method, by member name (linked only)
    calls: Dict[int, Dict[str, int]] = defaultdict(dict)
    for row in conn.execute(
            "SELECT r.from_symbol, t.name, MIN(r.line) AS line FROM code_refs r JOIN code_symbols t ON t.id = r.target_id "
            "WHERE r.codebase_id = ? AND r.kind = 'call' AND r.from_symbol IS NOT NULL GROUP BY r.from_symbol, t.name", (codebase_id,)):
        calls[row["from_symbol"]][row["name"]] = row["line"]

    # 1. A missing companion (accessors aren't companions of anything: getId goes with everything)
    for pair in patterns.pairs:
        if ACCESSOR.match(pair.first) or ACCESSOR.match(pair.second):
            continue
        for method_id, names in calls.items():
            if method_id not in symbols or pair.first not in names or pair.second in names:
                continue
            s = symbols[method_id]
            if TEST_NAMES.search(s["path"]):
                continue
            findings.append(Finding("companion", store.symbol(method_id), s["file_id"], s["path"], names[pair.first],
                                    f"`{pair.first}` goes with `{pair.second}` in {pair.support} of {pair.of} method{'s' if pair.of != 1 else ''} "
                                    f"({round(pair.confidence * 100)}%); this one calls `{pair.first}` without `{pair.second}`.",
                                    pair.examples, pair.confidence))

    # 2. A name against the package's convention
    for naming in patterns.naming:
        if naming.count < NAMING_MIN or naming.count / naming.total < NAMING_SHARE:
            continue
        for s in symbols.values():
            if s["kind"] in TYPE_KINDS and s["parent_id"] is None and not s["name"].endswith(naming.suffix) and not TEST_NAMES.search(s["path"]):
                package = conn.execute("SELECT package FROM code_files WHERE id = ?", (s["file_id"],)).fetchone()[0]
                if package == naming.package:
                    findings.append(Finding("naming", store.symbol(s["id"]), s["file_id"], s["path"], s["line"],
                                            f"{naming.count} of {naming.total} types in `{naming.package}` end in `{naming.suffix}`; `{s['name']}` doesn't.",
                                            naming.examples, round(naming.count / naming.total, 2)))

    # 3. An error raised nobody else raises
    if patterns.errors and patterns.errors[0].count >= ERROR_COMMON:
        for raised in patterns.errors:
            if raised.count == 1:
                where = raised.examples[0]
                owner = next((s for s in symbols.values() if s["file_id"] == where.file_id and s["line"] <= where.line <= s["end_line"]
                              and s["kind"] in ("method", "constructor", "function")), None)
                if owner is not None:
                    findings.append(Finding("error", store.symbol(owner["id"]), where.file_id, where.path, where.line,
                                            f"`{raised.type_name}` is thrown only here; `{patterns.errors[0].type_name}` is thrown {patterns.errors[0].count} times.",
                                            patterns.errors[0].examples, round(patterns.errors[0].count / (patterns.errors[0].count + 1), 2)))

    # 4. A route handler that doesn't call into the layer below, when its siblings all do
    handlers: Dict[int, List[int]] = defaultdict(list)
    for row in conn.execute("SELECT symbol_id FROM code_endpoints WHERE codebase_id = ? AND side = 'server' AND symbol_id IS NOT NULL", (codebase_id,)):
        s = conn.execute("SELECT parent_id FROM code_symbols WHERE id = ?", (row["symbol_id"],)).fetchone()
        if s and s["parent_id"] is not None:
            handlers[s["parent_id"]].append(row["symbol_id"])
    for owner, ids in handlers.items():
        if len(ids) < 3:
            continue
        calling = [i for i in ids if calls.get(i)]
        silent = [i for i in ids if not calls.get(i) and i in symbols]
        if len(calling) >= len(ids) - 1 and silent:
            for i in silent:
                s = symbols[i]
                findings.append(Finding("layering", store.symbol(i), s["file_id"], s["path"], s["line"],
                                        f"The other {len(calling)} handlers of this type call into the code; this one calls nothing the index links.",
                                        [Where(symbols[c]["file_id"], symbols[c]["path"], symbols[c]["line"], symbols[c]["qualified"]) for c in calling if c in symbols][:10],
                                        round(len(calling) / len(ids), 2)))
    return sorted(findings, key=lambda f: (f.path, f.line, f.kind))
