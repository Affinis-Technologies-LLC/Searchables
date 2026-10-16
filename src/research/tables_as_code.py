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
    shape: str = "enum"                             # "enum" (ADR-022) or "layout" (ADR-030)
    fields: List[dict] = field(default_factory=list)   # A layout's fields: property, constant, offset, width, code
    unit: str = ""
    total: int = 0
    notes: List[str] = field(default_factory=list)


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


def as_code(library: Library, block: TextBlock, language: str = "java", name: str = "", shape: str = "enum") -> AsCode:
    joined = library.joined_table(block)
    if joined is None:
        raise ValueError("That block isn't a table.")
    if shape == "layout":
        return render_layout(joined["caption"], joined["columns"], joined["rows"], language, name)
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


# ---- Field layouts (ADR-030) --------------------------------------------------------------------

_WIDTH_WORDS = re.compile(r"\b(bits?|width|length|len|size|bytes?|octets?)\b", re.I)
_POSITION_WORDS = re.compile(r"\b(start|offset|position|pos|no\.?)\b", re.I)
_RANGE = re.compile(r"^(?:bits?\s*)?(\d+)\s*(?:-|–|—|\.\.|to)\s*(\d+)$", re.I)
_NOT_FIELDS = re.compile(r"^(total|totals|sum)\b", re.I)
_SPARE = re.compile(r"^(spare|reserved|unused|padding|pad)\b", re.I)


@dataclass
class LayoutField:
    name: str           # As the table names it
    property: str       # referenceNumber
    constant: str       # REFERENCE_NUMBER
    offset: int
    width: int
    code: str = ""      # The code column's value, if the table has one ("281/001")


@dataclass
class Layout:
    unit: str                   # "bits", "bytes" or "octets", from the width column's heading
    positions: str              # "table" (a position or range column) or "computed" (from the widths, in row order)
    fields: List[LayoutField]
    total: int
    notes: List[str]            # Where the table doesn't add up: gaps, overlaps, a Total row that differs


def _unit_of(heading: str) -> str:
    word = _WIDTH_WORDS.search(heading)
    text = word.group(1).lower() if word else "bits"
    return "bytes" if text.startswith("byte") else "octets" if text.startswith("octet") else "bits"


def _column_values(rows: Sequence[Sequence[str]], i: int, name_col: int) -> List[str]:
    """A column's non-blank values, the Total row left out."""
    return [row[i].strip() for row in rows
            if i < len(row) and row[i].strip() and not _NOT_FIELDS.match(row[name_col].strip() if name_col < len(row) else "")]


def layout_of(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> Optional[Layout]:
    """
    The table as a field layout, or None when it has no width column: a number column headed by a
    width word, a range column ("0-18"), or the only other number column beside a position column.
    """
    classes = classify_columns(columns, rows)
    name_col = classes.index("name") if "name" in classes else next((i for i, c in enumerate(classes) if c == "text"), None)
    if name_col is None or not rows:
        return None
    range_col = width_col = position_col = None
    for i, heading in enumerate(columns):
        values = _column_values(rows, i, name_col)
        if i == name_col or not values:
            continue
        if sum(bool(_RANGE.match(v)) for v in values) >= 0.8 * len(values) and range_col is None:
            range_col = i
        elif classes[i] == "number":
            if _POSITION_WORDS.search(heading) and position_col is None:
                position_col = i
            elif _WIDTH_WORDS.search(heading) and width_col is None:
                width_col = i
    if width_col is None and position_col is not None and range_col is None:   # "Start bit | Length" with any heading for the length
        others = [i for i, c in enumerate(classes) if c == "number" and i not in (position_col, name_col)]
        width_col = others[0] if len(others) == 1 else None
    if width_col is None and range_col is None:
        return None
    unit = _unit_of(columns[width_col if width_col is not None else range_col])
    code_col = next((i for i, c in enumerate(classes) if c == "code" and i not in (name_col, width_col, position_col, range_col)), None)

    fields: List[LayoutField] = []
    notes: List[str] = []
    seen: dict = {}
    stated_total: Optional[int] = None
    cursor = 0
    spares = 0
    for row in rows:
        cell = lambda i: row[i].strip() if i is not None and i < len(row) else ""
        name = cell(name_col)
        if _NOT_FIELDS.match(name):
            if cell(width_col).isdigit():
                stated_total = int(cell(width_col))
            continue
        if range_col is not None and _RANGE.match(cell(range_col)):
            start, end = (int(n) for n in _RANGE.match(cell(range_col)).groups())
            offset, width = min(start, end), abs(end - start) + 1
        else:
            if not cell(width_col).isdigit():
                notes.append(f"{name or 'A row'} has no whole-number width ({cell(width_col) or 'blank'}) and was left out.")
                continue
            width = int(cell(width_col))
            offset = int(cell(position_col)) if position_col is not None and cell(position_col).isdigit() else cursor
        if not name or _SPARE.match(name):
            spares += 1
            base = f"SPARE_{spares}"
        else:
            base = constant_name(name)
        constant, n = base, 2
        while constant in seen:
            constant, n = f"{base}_{n}", n + 1
        seen[constant] = True
        words = constant.lower().split("_")
        prop = words[0] + "".join(w[:1].upper() + w[1:] for w in words[1:])
        fields.append(LayoutField(name or constant, prop, constant, offset, width, cell(code_col)))
        cursor = offset + width
    for a, b in zip(fields, fields[1:]):
        gap = b.offset - (a.offset + a.width)
        if gap > 0:
            notes.append(f"A gap of {gap} {unit[:-1] if gap == 1 else unit} between {a.name} and {b.name}.")
        elif gap < 0:
            notes.append(f"{a.name} and {b.name} overlap by {-gap} {unit[:-1] if gap == -1 else unit}.")
    total = max((f.offset + f.width for f in fields), default=0)
    if stated_total is not None and stated_total != total:
        notes.append(f"The Total row says {stated_total} {unit}; the fields add up to {total}.")
    positions = "table" if range_col is not None or position_col is not None else "computed"
    return Layout(unit, positions, fields, total, notes)


def _bits(layout_field: LayoutField, unit: str) -> int:
    return layout_field.width * (1 if unit == "bits" else 8)


def _java_type(layout_field: LayoutField, unit: str) -> str:
    bits = _bits(layout_field, unit)
    return "boolean" if bits == 1 else "int" if bits <= 31 else "long" if bits <= 63 else "byte[]"


def _ts_type(layout_field: LayoutField, unit: str) -> str:
    bits = _bits(layout_field, unit)
    return "boolean" if bits == 1 else "number" if bits <= 53 else "bigint"


def render_layout(caption: str, columns: Sequence[str], rows: Sequence[Sequence[str]], language: str, name: str = "") -> AsCode:
    """The table as a Java record or a TypeScript interface, with its offsets and widths beside it (ADR-030)."""
    layout = layout_of(columns, rows)
    if layout is None:
        raise ValueError("That table has no width column, so it isn't a field layout.")
    name = name or _caption_name(caption)
    unit = layout.unit
    where = "as the table gives them" if layout.positions == "table" else "computed from 0 in row order"
    header = f"/** From {caption.strip()} · {layout.total} {unit}, offsets {where} */" if caption else f"/** {layout.total} {unit}, offsets {where} */"
    lines = [header]
    if language == "java":
        components = ", ".join(f"{_java_type(f, unit)} {f.property}" for f in layout.fields)
        lines.append(f"public record {name}({components}) {{")
        suffix = unit.upper()
        for f in layout.fields:
            comment = f"   // {f.code}" if f.code else ""
            lines.append(f"    public static final int {f.constant}_OFFSET = {f.offset}, {f.constant}_{suffix} = {f.width};{comment}")
        lines.append(f"    public static final int TOTAL_{suffix} = {layout.total};")
        lines.append("}")
    else:
        properties = "; ".join(f"{f.property}: {_ts_type(f, unit)}" for f in layout.fields)
        lines.append(f"export interface {name} {{ {properties} }}")
        lines.append(f"export const {name}Layout = {{")
        for f in layout.fields:
            comment = f"   // {f.code}" if f.code else ""
            lines.append(f"  {f.property}: {{ offset: {f.offset}, {unit}: {f.width} }},{comment}")
        lines.append(f"  total{unit[:1].upper()}{unit[1:]}: {layout.total},")
        lines.append("} as const;")
    return AsCode(name, language, "\n".join(lines), [f.constant for f in layout.fields], list(columns), classify_columns(columns, rows),
                  shape="layout", fields=[vars(f) for f in layout.fields], unit=unit, total=layout.total, notes=layout.notes)


@dataclass
class Difference:
    field: str
    what: str       # "offset" or the unit ("bits", "bytes", "octets")
    table: int
    code: int


@dataclass
class TypeComparison:
    type: Symbol
    matched: List[str]
    missing_in_code: List[str]
    extra_in_code: List[str]
    extra: List[ExtraConstant]
    differences: List[Difference]
    not_stated: List[str]       # "referenceNumber offset": the code declares no constant for it
    by_name_only: bool          # No constant of the template's convention exists, so only names were compared


_CONSTANT_VALUE = re.compile(r"\b{name}\s*=\s*(\d+)")
_WIDTH_SUFFIXES = ("_BITS", "_WIDTH", "_BYTES", "_OCTETS", "_LENGTH", "_SIZE")
_OFFSET_SUFFIXES = ("_OFFSET", "_START", "_POSITION")


def compare_with_type(library: Library, store: CodeStore, block: TextBlock, symbol: Symbol) -> TypeComparison:
    """The layout's fields against a class, record or interface of a codebase, widths read from its constants."""
    joined = library.joined_table(block)
    if joined is None:
        raise ValueError("That block isn't a table.")
    layout = layout_of(joined["columns"], joined["rows"])
    if layout is None:
        raise ValueError("That table has no width column, so it isn't a field layout.")
    members = [m for m in store.members(symbol.id) if m.kind == "field"]
    fields = [m for m in members if not m.name.isupper()]
    constants = {m.name: m for m in members if m.name.isupper()}
    for s in store.outline(symbol.file_id):   # The file's own constants count too (a TypeScript file's `const X_BITS`)
        if s.kind in ("field", "variable") and s.name.isupper() and s.name not in constants:
            constants[s.name] = s

    def normal(name: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", name.upper())
    declared_by_normal = {normal(f.name): f.name for f in fields}
    lines = store.lines(symbol.file_id)

    def value_of(constant: str) -> Optional[int]:
        s = constants.get(constant)
        if s is None or not 0 < s.line <= len(lines):
            return None
        found = re.search(_CONSTANT_VALUE.pattern.format(name=re.escape(constant)), lines[s.line - 1])
        return int(found.group(1)) if found else None

    matched, missing, differences, not_stated = [], [], [], []
    for f in layout.fields:
        actual = declared_by_normal.get(normal(f.property))
        if actual is None:
            missing.append(f.property)
            continue
        matched.append(actual)
        for what, suffixes, table_value in ((layout.unit, _WIDTH_SUFFIXES, f.width), ("offset", _OFFSET_SUFFIXES, f.offset)):
            values = [v for v in (value_of(f.constant + s) for s in suffixes) if v is not None]
            if not values:
                not_stated.append(f"{actual} {what}")
            elif values[0] != table_value:
                differences.append(Difference(actual, what, table_value, values[0]))
    matched_set = set(matched)
    extra = [ExtraConstant(m.name, m.id, m.line) for m in fields if m.name not in matched_set]
    by_name_only = bool(matched) and len(not_stated) == 2 * len(matched)
    return TypeComparison(symbol, matched, missing, [e.name for e in extra], extra, differences, not_stated, by_name_only)
