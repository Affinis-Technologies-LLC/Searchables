"""Tables as data (ADR-022): a standard's table as an enum, and compared with the enum the code has."""
import sqlite3
from pathlib import Path

import pytest

from src.code.store import CodeStore
from src.research.tables_as_code import as_code, classify_columns, compare_with_enum, constant_name
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
