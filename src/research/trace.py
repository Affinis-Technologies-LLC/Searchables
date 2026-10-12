"""
Traceability as mentions (ADR-014): where a Catalogue identifier's text appears in the code
(exact), or a symbol is named after it (by name), and which identifiers a file mentions. Nothing
is claimed about implementation; the certainty says what was found.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.code.store import CodeStore
from src.search.library import Library

_PAIR = re.compile(r"^[A-Za-z]+(?:/[A-Za-z]+)?\s+(\d+(?:/\d+)+)$")


def _compact(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def name_forms(identifier: str) -> List[str]:
    """The forms an identifier may take in code: as written, its numeric core for pairs, and a compacted name."""
    text = identifier.strip()
    if len(text) < 3 or text.isdigit():
        return []
    forms = [text]
    pair = _PAIR.match(text)
    if pair:
        forms.append(pair.group(1))
    compact = _compact(text)
    if compact and compact != text and len(compact) >= 3 and not compact.isdigit():
        forms.append(compact)
    return forms


@dataclass
class Mention:
    codebase_id: int
    file_id: int
    path: str
    line: int
    text: str
    certainty: str              # exact, name
    symbol: str = ""            # By-name mentions: the symbol named after the identifier
    changed: str = ""           # When the line last changed, from git blame (ADR-026); "" without a repository or not committed


@dataclass
class FileIdentifier:
    identifier: str
    line: int
    certainty: str
    text: str


def code_mentions(library: Library, store: CodeStore, identifier: str, codebase_ids: Optional[Sequence[int]] = None) -> List[Mention]:
    forms = name_forms(identifier)
    if not forms:
        return []
    text_forms = [f for f in forms if f != _compact(identifier) or f == identifier]
    compact = _compact(identifier)
    found: dict = {}
    for codebase in store.list_codebases():
        if codebase_ids and codebase.id not in codebase_ids:
            continue
        for form in text_forms:
            for file, line, text in store.search_text(codebase.id, form, limit=2000):
                if form in text:   # Case matters for identifiers
                    found.setdefault((file.id, line), Mention(codebase.id, file.id, file.path, line, text.strip(), "exact"))
        for row in store.conn.execute(
                "SELECT s.id, s.qualified, s.line, s.file_id, f.path FROM code_symbols s JOIN code_files f ON f.id = s.file_id "
                "WHERE s.codebase_id = ? AND UPPER(REPLACE(REPLACE(REPLACE(REPLACE(s.name, '_', ''), '.', ''), '/', ''), '-', '')) = ?",
                (codebase.id, compact)):
            line_text = store.lines(row["file_id"])[row["line"] - 1].strip() if row["line"] <= len(store.lines(row["file_id"])) else ""
            found.setdefault((row["file_id"], row["line"]), Mention(codebase.id, row["file_id"], row["path"], row["line"], line_text, "name", row["qualified"]))
    return sorted(found.values(), key=lambda m: (m.path, m.line))


def identifiers_in_file(library: Library, store: CodeStore, file_id: int) -> List[FileIdentifier]:
    """The Catalogue's identifiers (switched-on families) mentioned in a file, with lines."""
    file = store.file(file_id)
    if file is None:
        return []
    lines = store.lines(file_id)
    text_lines = [(n, line) for n, line in enumerate(lines, 1)]
    results: List[FileIdentifier] = []
    seen = set()
    compact_names = {}
    for symbol in store.outline(file_id):
        compact_names.setdefault(_compact(symbol.name), symbol.line)
    for entry in library.catalogue():
        value = entry["value"]
        forms = name_forms(value)
        if not forms:
            continue
        compact = _compact(value)
        exact_forms = [f for f in forms if f != compact or f == value]
        for n, line in text_lines:
            if any(f in line for f in exact_forms) and (value, n) not in seen:
                seen.add((value, n))
                results.append(FileIdentifier(value, n, "exact", line.strip()))
        if compact in compact_names and (value, compact_names[compact]) not in seen:
            n = compact_names[compact]
            seen.add((value, n))
            results.append(FileIdentifier(value, n, "name", lines[n - 1].strip() if n <= len(lines) else ""))
    return sorted(results, key=lambda i: (i.line, i.identifier))
