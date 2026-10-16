"""Tables as data (ADR-022): a standard's table as an enum, and compared with the enum the code has."""
import sqlite3
from pathlib import Path

import pytest

from src.code.store import CodeStore
from src.research.tables_as_code import as_code, classify_columns, compare_with_enum, compare_with_type, constant_name, layout_of, render_layout
from tests.conftest import MESSAGE_FOOTERS, make_pdf, message_standard


@pytest.fixture
def doc(library, extractor, model):
    document, _ = library.add_document(make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), "XYZ-STD-9999A.pdf", extractor)
    return document


def table_named(library, doc, caption_start):
    return next(b for b in library.document_blocks(doc.id) if b.kind == "table" and b.text.startswith(caption_start))


def test_constant_names_and_column_classes():
    assert constant_name("Reference Number") == "REFERENCE_NUMBER"
    assert constant_name("Course (true)") == "COURSE_TRUE"
    assert constant_name("3D position") == "_3D_POSITION"
    classes = classify_columns(["FIELD", "GRP/ITM", "BITS"], [["Reference Number", "281/001", "19"], ["Strength", "755/002", "4"]])
    assert classes == ["name", "code", "number"]


def test_a_table_renders_as_java_and_typescript(library, doc):
    table = table_named(library, doc, "TABLE 5.1-1")
    java = as_code(library, table, "java")
    assert java.name == "M32IInitialWord" and java.constants == ["REFERENCE_NUMBER", "STRENGTH"]
    assert 'REFERENCE_NUMBER("281/001", 19)' in java.text and 'STRENGTH("755/002", 4)' in java.text
    assert "public enum M32IInitialWord" in java.text and "private final String grpItm;" in java.text and "private final int bits;" in java.text
    ts = as_code(library, table, "typescript", name="InitialWord")
    assert "export const InitialWord = {" in ts.text and 'REFERENCE_NUMBER: { field: "Reference Number", grpItm: "281/001", bits: 19 }' in ts.text and ts.text.rstrip().endswith("} as const;")
    joined = as_code(library, table_named(library, doc, "TABLE 5.1-2"), "java")
    assert joined.constants == ["COURSE", "SPEED", "ALTITUDE", "IDENTITY"]           # Joined across the continuation


def test_compared_with_the_enum_in_the_code(library, doc, tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code/Fields.java").write_text("""package p;

public enum Fields {
    REFERENCE_NUMBER("281/001", 19),
    STRENGTH("755/002", 5),
    COURSE("371/001", 9);

    private final String grpItm;
    private final int bits;

    Fields(String grpItm, int bits) { this.grpItm = grpItm; this.bits = bits; }
}
""")
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(tmp_path / "code"), "Fields")
    store.index(codebase.id)
    enum = next(s for s in store.search_symbols(codebase.id, "Fields") if s.kind == "enum")
    result = compare_with_enum(library, store, table_named(library, doc, "TABLE 5.1-1"), enum)
    assert result.matched == ["REFERENCE_NUMBER", "STRENGTH"] and result.missing_in_code == [] and result.extra_in_code == ["COURSE"]
    assert result.value_mismatches == [("STRENGTH", "4")]          # The table says 4 bits; the code says 5
    result = compare_with_enum(library, store, table_named(library, doc, "TABLE 5.1-2"), enum)
    assert result.matched == ["COURSE"] and result.missing_in_code == ["SPEED", "ALTITUDE", "IDENTITY"] and result.extra_in_code == ["REFERENCE_NUMBER", "STRENGTH"]
    assert result.enum.qualified == "p.Fields" and all(c.symbol_id for c in result.extra)


# ---- Field layouts (ADR-030) --------------------------------------------------------------------


def test_a_layout_is_recognised_from_its_width_column():
    layout = layout_of(["FIELD", "GRP/ITM", "BITS"], [["Reference Number", "281/001", "19"], ["Strength", "755/002", "4"]])
    assert layout.unit == "bits" and layout.positions == "computed" and layout.total == 23 and layout.notes == []
    assert [(f.property, f.constant, f.offset, f.width, f.code) for f in layout.fields] == \
        [("referenceNumber", "REFERENCE_NUMBER", 0, 19, "281/001"), ("strength", "STRENGTH", 19, 4, "755/002")]
    assert layout_of(["Acronym", "Meaning"], [["RN", "Reference Number"], ["NU", "Network Unit"]]) is None   # No width
    assert layout_of(["Message", "Field", "Purpose"], [["K3.5", "Item position", "Where an item is"]]) is None

    # Positions as written; a Total row is checked, not a field; a Spare row occupies its bits
    layout = layout_of(["Field", "Start bit", "Length"], [["Flag", "0", "1"], ["Spare", "1", "3"], ["Count", "4", "8"], ["Total", "", "12"]])
    assert layout.positions == "table" and layout.total == 12 and layout.notes == []
    assert [(f.property, f.constant, f.offset, f.width) for f in layout.fields] == [("flag", "FLAG", 0, 1), ("spare1", "SPARE_1", 1, 3), ("count", "COUNT", 4, 8)]

    # A range column gives both the offset and the width; a gap is said, not closed
    layout = layout_of(["Field", "Bits"], [["Mode", "0-2"], ["Value", "4–11"]])
    assert layout.unit == "bits" and layout.positions == "table" and [(f.offset, f.width) for f in layout.fields] == [(0, 3), (4, 8)]
    assert layout.total == 12 and layout.notes == ["A gap of 1 bit between Mode and Value."]

    # Bytes stay bytes; a Total row that doesn't add up is a note
    layout = layout_of(["Field", "Octets"], [["Header", "2"], ["Body", "6"], ["Total", "9"]])
    assert layout.unit == "octets" and layout.total == 8 and layout.notes == ["The Total row says 9 octets; the fields add up to 8."]
    layout = layout_of(["Field", "Bits"], [["A", "0-3"], ["B", "2-5"]])
    assert layout.notes == ["A and B overlap by 2 bits."]


def test_a_layout_renders_as_a_record_and_an_interface(library, doc):
    table = table_named(library, doc, "TABLE 5.1-1")
    java = as_code(library, table, "java", shape="layout")
    assert java.shape == "layout" and java.name == "M32IInitialWord" and java.unit == "bits" and java.total == 23
    assert java.text == """/** From TABLE 5.1-1. M3.2I initial word · 23 bits, offsets computed from 0 in row order */
public record M32IInitialWord(int referenceNumber, int strength) {
    public static final int REFERENCE_NUMBER_OFFSET = 0, REFERENCE_NUMBER_BITS = 19;   // 281/001
    public static final int STRENGTH_OFFSET = 19, STRENGTH_BITS = 4;   // 755/002
    public static final int TOTAL_BITS = 23;
}"""
    ts = as_code(library, table, "typescript", shape="layout", name="InitialWord")
    assert ts.text == """/** From TABLE 5.1-1. M3.2I initial word · 23 bits, offsets computed from 0 in row order */
export interface InitialWord { referenceNumber: number; strength: number }
export const InitialWordLayout = {
  referenceNumber: { offset: 0, bits: 19 },   // 281/001
  strength: { offset: 19, bits: 4 },   // 755/002
  totalBits: 23,
} as const;"""
    joined = as_code(library, table_named(library, doc, "TABLE 5.1-2"), "java", shape="layout")
    assert [(f["property"], f["offset"], f["width"]) for f in joined.fields] == [("course", 0, 9), ("speed", 9, 11), ("altitude", 20, 13), ("identity", 33, 3)]
    assert joined.total == 36 and "public record M32E0ExtensionWord(int course, int speed, int altitude, int identity)" in joined.text
    # The enum rendering is unchanged
    assert as_code(library, table, "java").constants == ["REFERENCE_NUMBER", "STRENGTH"]


def test_types_follow_the_width():
    rows = [["Flag", "1"], ["Count", "12"], ["Clock", "40"], ["Blob", "80"]]
    java = render_layout("TABLE 9. Mixed", ["Field", "Bits"], rows, "java").text
    assert "public record Mixed(boolean flag, int count, long clock, byte[] blob)" in java
    ts = render_layout("TABLE 9. Mixed", ["Field", "Bits"], rows, "typescript").text
    assert "export interface Mixed { flag: boolean; count: number; clock: number; blob: bigint }" in ts
    octets = render_layout("TABLE 10. Header", ["Field", "Octets"], [["Kind", "1"], ["Length", "2"], ["Id", "6"]], "java").text
    assert "public record Header(int kind, int length, long id)" in octets and "KIND_OFFSET = 0, KIND_OCTETS = 1" in octets and "TOTAL_OCTETS = 9" in octets
    with pytest.raises(ValueError, match="width column"):
        render_layout("TABLE 11. Codes", ["Code", "Meaning"], [["A", "Alpha"]], "java")


def test_compared_with_the_record_in_the_code(library, doc, tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code/InitialWord.java").write_text("""package p;

public record InitialWord(int referenceNumber, int strength, int course) {
    public static final int REFERENCE_NUMBER_BITS = 19;
    public static final int STRENGTH_OFFSET = 19, STRENGTH_BITS = 5;
}
""")
    (tmp_path / "code/word.ts").write_text("""export interface InitialWord { referenceNumber: number; strength: number; course: number }
export const InitialWordLayout = { referenceNumber: { offset: 0, bits: 19 }, strength: { offset: 19, bits: 5 } } as const;
""")
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(tmp_path / "code"), "Words")
    store.index(codebase.id)
    record = next(s for s in store.search_symbols(codebase.id, "InitialWord") if s.kind == "record")
    result = compare_with_type(library, store, table_named(library, doc, "TABLE 5.1-1"), record)
    assert result.matched == ["referenceNumber", "strength"] and result.missing_in_code == [] and result.extra_in_code == ["course"]
    assert [(d.field, d.what, d.table, d.code) for d in result.differences] == [("strength", "bits", 4, 5)]   # The table says 4 bits
    assert result.not_stated == ["referenceNumber offset"] and result.type.qualified == "p.InitialWord"
    assert all(e.symbol_id for e in result.extra) and result.by_name_only is False
    result = compare_with_type(library, store, table_named(library, doc, "TABLE 5.1-2"), record)
    assert result.matched == ["course"] and result.missing_in_code == ["speed", "altitude", "identity"] and result.extra_in_code == ["referenceNumber", "strength"]

    interface = next(s for s in store.search_symbols(codebase.id, "InitialWord") if s.kind == "interface")
    result = compare_with_type(library, store, table_named(library, doc, "TABLE 5.1-1"), interface)
    assert result.matched == ["referenceNumber", "strength"] and result.extra_in_code == ["course"]
    assert result.differences == [] and result.by_name_only is True   # The layout object's values aren't symbols
