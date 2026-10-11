"""
Tables as data (ADR-022): a standard's table rendered as a Java enum or a TypeScript constant
object, deterministically, and compared with the enum a codebase already has. No AI: a template over
the table's columns, classified by what their values look like.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from src.code.models import Symbol
from src.code.store import CodeStore
from src.models import TextBlock
from src.search.library import Library

_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
_CODE = re.compile(r"^(?=.*\d)[A-Za-z0-9][\w./:-]*$|^0x[0-9A-Fa-f]+$|^[A-Z]{1,4}-?\d+$")
_WORDS = re.compile(r"^[A-Za-z][A-Za-z ,()'/-]*$")


def constant_name(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    name = "_".join(w.upper() for w in words) or "UNNAMED"
    return "_" + name if name[0].isdigit() else name


def type_name(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    name = "".join(w[:1].upper() + w[1:] for w in words) or "Table"
    return "T" + name if name[0].isdigit() else name


def field_name(column: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", column)
    if not words:
        return "value"
    name = words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    return "_" + name if name[0].isdigit() else name


def classify_columns(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    """"name", "code", "number" or "text" per column, from what most of its values look like."""
    classes = []
    for i in range(len(columns)):
        values = [row[i].strip() for row in rows if i < len(row) and row[i].strip()]
        if not values:
            classes.append("text")
            continue
        numbers = sum(bool(_NUMBER.match(v)) for v in values)
        codes = sum(bool(_CODE.match(v)) and not _NUMBER.match(v) for v in values)
        words = sum(bool(_WORDS.match(v)) for v in values)
        if numbers >= 0.8 * len(values):
            classes.append("number")
        elif codes >= 0.6 * len(values):
            classes.append("code")
        elif words >= 0.6 * len(values):
            classes.append("name")
        else:
            classes.append("text")
    if "name" not in classes:   # The first text-like column names the rows
        for i, c in enumerate(classes):
            if c == "text":
                classes[i] = "name"
                break
    else:
        first = classes.index("name")
        classes = [("text" if c == "name" and i != first else c) for i, c in enumerate(classes)]
    return classes


@dataclass
class AsCode:
    name: str
    language: str
    text: str
    constants: List[str]
    columns: List[str]
    classes: List[str]


def _caption_name(caption: str) -> str:
    text = re.sub(r"^\s*(TABLE|Table)\s+[\w.-]+\s*[.:—-]?\s*", "", caption or "").strip()
    return type_name(text) if text else "Table"


def _literal(value: str, kind: str, java: bool) -> str:
    value = value.strip()
    if kind == "number" and _NUMBER.match(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render(caption: str, columns: Sequence[str], rows: Sequence[Sequence[str]], language: str, name: str = "") -> AsCode:
    classes = classify_columns(columns, rows)
    name = name or _caption_name(caption)
    name_col = classes.index("name") if "name" in classes else 0
    others = [i for i in range(len(columns)) if i != name_col]
    constants = []
    seen = set()
    for row in rows:
        base = constant_name(row[name_col] if name_col < len(row) else "")
        candidate, n = base, 2
        while candidate in seen:
            candidate, n = f"{base}_{n}", n + 1
        seen.add(candidate)
        constants.append(candidate)
    lines = []
    if language == "java":
        lines.append(f"/** From {caption.strip()} */" if caption else "")
        lines.append(f"public enum {name} {{")
        for constant, row in zip(constants, rows):
            args = ", ".join(_literal(row[i] if i < len(row) else "", classes[i], True) for i in others)
            lines.append(f"    {constant}({args}),")
        if rows:
            lines[-1] = lines[-1][:-1] + ";"
        lines.append("")
        for i in others:
            lines.append(f"    private final {'int' if classes[i] == 'number' else 'String'} {field_name(columns[i])};")
        params = ", ".join(f"{'int' if classes[i] == 'number' else 'String'} {field_name(columns[i])}" for i in others)
        lines.append("")
        lines.append(f"    {name}({params}) {{")
        for i in others:
            lines.append(f"        this.{field_name(columns[i])} = {field_name(columns[i])};")
        lines.append("    }")
        for i in others:
            f = field_name(columns[i])
            lines.append("")
            lines.append(f"    public {'int' if classes[i] == 'number' else 'String'} {f}() {{ return {f}; }}")
        lines.append("}")
    else:
        lines.append(f"/** From {caption.strip()} */" if caption else "")
        lines.append(f"export const {name} = {{")
        for constant, row in zip(constants, rows):
            fields = ", ".join(f"{field_name(columns[i])}: {_literal(row[i] if i < len(row) else '', classes[i], False)}" for i in range(len(columns)))
            lines.append(f"  {constant}: {{ {fields} }},")
        lines.append("} as const;")
    return AsCode(name, language, "\n".join(l for l in lines if l is not None).lstrip("\n"), constants, list(columns), classes)


def as_code(library: Library, block: TextBlock, language: str = "java", name: str = "") -> AsCode:
    joined = library.joined_table(block)
    if joined is None:
        raise ValueError("That block isn't a table.")
    return render(joined["caption"], joined["columns"], joined["rows"], language, name)


@dataclass
class ExtraConstant:
    name: str
    symbol_id: int
    line: int


@dataclass
class Comparison:
    enum: Symbol
    matched: List[str]
    missing_in_code: List[str]
    extra_in_code: List[str]
    extra: List[ExtraConstant]
    value_mismatches: List[Tuple[str, str]]   # (constant, a table value the declaration doesn't contain)


def compare_with_enum(library: Library, store: CodeStore, block: TextBlock, enum: Symbol) -> Comparison:
    joined = library.joined_table(block)
    if joined is None:
        raise ValueError("That block isn't a table.")
    code = render(joined["caption"], joined["columns"], joined["rows"], "java")
    members = [m for m in store.members(enum.id) if m.kind == "field" and m.name.isupper()]   # Constants, not the enum's own fields
    declared = {m.name: m for m in members}
    table_names = {c: row for c, row in zip(code.constants, joined["rows"])}

    def normal(name: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", name.upper())
    declared_by_normal = {normal(n): n for n in declared}
    matched, missing, mismatches = [], [], []
    for constant, row in table_names.items():
        actual = declared_by_normal.get(normal(constant))
        if actual is None:
            missing.append(constant)
            continue
        matched.append(actual)
        declaration = declared[actual].signature
        for i, cls in enumerate(code.classes):
            if cls in ("code", "number") and i < len(row) and row[i].strip() and row[i].strip() not in declaration:
                mismatches.append((actual, row[i].strip()))
    matched_set = set(matched)
    extra = [ExtraConstant(m.name, m.id, m.line) for m in members if m.name not in matched_set]
    return Comparison(enum, matched, missing, [e.name for e in extra], extra, mismatches)
