"""Traceability as mentions (ADR-014): where an identifier's text appears in the code, and back."""
import sqlite3
from pathlib import Path

import pytest

from src.code.store import CodeStore
from src.research.trace import code_mentions, identifiers_in_file, name_forms
from tests.conftest import MESSAGE_FOOTERS, make_pdf, message_standard

CODE = """package p;

public class Message {
    public static final String REFERENCE_NUMBER_FIELD = "GRP/ITM 281/001";   // the RN
    public static final int M3_2 = 32;
    public int strength = 0;   // see 755/002

    public void send(String label) {
        if (label.equals("M3.2")) { strength++; }
    }
}
"""


@pytest.fixture
def doc(library, extractor, model):
    document, _ = library.add_document(make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), "XYZ-STD-9999A.pdf", extractor)
    return document


@pytest.fixture
def store(tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code/Message.java").write_text(CODE)
    conn = sqlite3.connect(tmp_path / "library.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store = CodeStore(conn)
    codebase = store.add(str(tmp_path / "code"), "Msg")
    store.index(codebase.id)
    return store


def test_name_forms():
    assert name_forms("GRP/ITM 281/001") == ["GRP/ITM 281/001", "281/001", "GRPITM281001"]
    assert name_forms("M3.2") == ["M3.2", "M32"]
    assert name_forms("12") == []           # Too short to mean anything


def test_an_identifier_to_the_code(library, doc, store):
    mentions = code_mentions(library, store, "GRP/ITM 281/001")
    assert [(m.line, m.certainty) for m in mentions] == [(4, "exact")]
    assert mentions[0].path.endswith("Message.java") and "281/001" in mentions[0].text
    mentions = code_mentions(library, store, "M3.2")
    assert [(m.line, m.certainty, m.symbol) for m in mentions] == [(5, "name", "p.Message#M3_2"), (9, "exact", "")]
    assert code_mentions(library, store, "755/002")[0].line == 6 or code_mentions(library, store, "GRP/ITM 755/002")[0].line == 6


def test_a_file_to_the_identifiers(library, doc, store):
    file = next(f for f in store.files(store.list_codebases()[0].id) if f.path.endswith("Message.java"))
    found = identifiers_in_file(library, store, file.id)
    # The Catalogue's identifiers (families switched on); the M#.# family is off in this small fixture, so M3.2 isn't listed
    assert [(i.identifier, i.line, i.certainty) for i in found] == [("GRP/ITM 281/001", 4, "exact"), ("GRP/ITM 755/002", 6, "exact")]
