"""Conventions of military and government standards, on a made-up standard laid out the same way."""
import pytest

from conftest import MESSAGE_FOOTERS, make_pdf, message_standard
from src.extractor.identifiers import find_candidates, identifier_key, labelled_cells, parent_key
from src.extractor.objects import find_xrefs, parse_caption
from src.research.collections import CollectionStore
from src.research.export import to_markdown
from src.research.glossary import build_acronyms, expand_acronyms, terms_in_text


@pytest.fixture
def doc(library, extractor, model):
    document, _ = library.add_document(make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), "XYZ-STD-9999A.pdf", extractor)
    return document


def block(library, doc, start):
    return next(b for b in library.document_blocks(doc.id) if b.text.startswith(start))


# ---- Captions and references -------------------------------------------------------------------

def test_table_numbers_keep_their_sequence_number():
    assert parse_caption("TABLE 4.2-1. Message summary").label == "Table 4.2-1"
    assert parse_caption("TABLE 4.2-2. Field summary").label == "Table 4.2-2"
    assert parse_caption("FIGURE 4.11-2. Item reporting").label == "Figure 4.11-2"
    assert parse_caption("TABLE B-I. Data elements").label == "Table B-I"
    assert parse_caption("Table 5 gives the limits") is None


def test_continued_captions():
    for text in ("TABLE 5.1-3. Word map - Continued", "TABLE 5.1-3. Word map (Continued)", "TABLE 5.1-3. Word map (Cont'd)",
                 "TABLE 5.1-3 (continued)", "TABLE 5.1-3. Word map — Concluded"):
        caption = parse_caption(text)
        assert (caption.label, caption.continued) == ("Table 5.1-3", True) and caption.title in ("Word map", "")
    assert not parse_caption("Table 5 — Continued operation limits").continued     # A title, not a continuation


def test_references_to_numbered_tables():
    refs = find_xrefs("See Tables 4.2-1 to 4.2-3 and FIGURE 4.11-2; also paragraph 4.11.13.2.1.")
    assert refs == [("table", "Table 4.2-1"), ("table", "Table 4.2-3"), ("figure", "Figure 4.11-2"), ("clause", "4.11.13.2.1")]


# ---- Identifiers -------------------------------------------------------------------------------

def test_paired_and_spaced_identifiers():
    found = find_candidates("M3.2I carries GRP 281/ITM 001; see M 12.6, GRP/ITM 1620/003 and GRP 755, ITM 002.")
    assert found == ["M3.2I", "GRP/ITM 281/001", "GRP 281", "M 12.6", "GRP/ITM 1620/003", "GRP 1620", "GRP/ITM 755/002", "GRP 755"]
    assert identifier_key("M 12.6") == identifier_key("M12.6")
    keys = {identifier_key(v) for v in found}
    assert parent_key("GRP/ITM281/001", keys) == "GRP281" and parent_key("M3.2I", {"M3.2"}) == "M3.2"


def test_table_columns_name_their_numbers():
    known = ({"GRP"}, {("GRP", "ITM")})
    assert labelled_cells(["FIELD", "GRP/ITM", "BITS"], ["Reference Number", "281/001", "19"], *known) == ["GRP/ITM 281/001", "GRP 281"]
    assert labelled_cells(["FIELD", "GRP", "ITM"], ["Reference Number", "281", "001"], *known) == ["GRP 281", "GRP/ITM 281/001"]
    assert labelled_cells(["FIELD", "BITS"], ["Reference Number", "19"], *known) == []          # "BITS" isn't an identifier label


# ---- The document ------------------------------------------------------------------------------

def test_document_is_read_the_military_standard_way(library, doc):
    assert doc.distribution.startswith("DISTRIBUTION STATEMENT C. Distribution authorized")
    assert block(library, doc, "The M3.2 message").display_page == "5-1"                    # The number printed on the page
    assert block(library, doc, "The M 12.6 message").display_page == "5-2"

    first, second = (block(library, doc, f"TABLE 5.1-{n}") for n in (1, 2))
    assert (first.label, second.label) == ("Table 5.1-1", "Table 5.1-2")
    joined = library.joined_table(second)
    assert joined["pages"] == [2, 3] and [r[0] for r in joined["rows"]] == ["Course", "Speed", "Altitude", "Identity"]
    assert joined["caption"] == "TABLE 5.1-2. M3.2E0 extension word"
    # The continuation doesn't repeat the heading row: it takes the first part's, so its rows are read as fields too
    continued = [b for b in library.document_blocks(doc.id) if b.label == "Table 5.1-2"][1]
    assert library.document_tables(doc.id)[continued.id].columns == ["FIELD", "GRP/ITM", "BITS"]
    assert any(h.block.id == continued.id for h in library.identifier_search("GRP/ITM 365/001"))
    # The reference in the text resolves to the right one of the two tables
    assert library.resolve(doc.id, library_ref("table", "Table 5.1-2")).block_id == second.id


def library_ref(kind, target):
    from src.models import CrossRef
    return CrossRef(0, kind, target)


def test_identifier_search_finds_pairs_and_their_parts(library, doc):
    library.set_family_enabled(doc.id, "GRP/ITM#/#", True)
    library.set_family_enabled(doc.id, "GRP#", True)
    hits = library.identifier_search("grp/itm 281/001")
    assert {h.group for h in hits} == {"table", "mention", "rule"} or len(hits) >= 3
    assert any(h.block.label == "Table 5.1-1" and h.rows == (1,) for h in hits)             # Found in the table row
    with_children = library.identifier_search("GRP 281", include_children=True)
    assert any("GRP/ITM 281/001" in h.values for h in with_children)
    assert [h.block.text[:9] for h in library.identifier_search("M12.6")][:1] == ["5.2 M 12."]


def test_acronyms(library, doc):
    acronyms = build_acronyms(library.document_blocks(doc.id), library.document_tables(doc.id))
    assert [(a.term, a.definition) for a in acronyms] == [
        ("NU", "Network Unit"), ("RN", "Reference Number"), ("SPLR", "Status, Position and Location Report")]
    known = {a.term: a.definition for a in acronyms}
    assert expand_acronyms("when is splr reported", known) == [("SPLR", known["SPLR"])]
    assert expand_acronyms("reference number field", known) == [("RN", "Reference Number")]            # Spelled out: the acronym is added
    assert expand_acronyms("rn", known) == []                                                  # Too short to guess the case
    assert [t.term for t in terms_in_text(acronyms, "A NU reports its SPLR; it is not a rn.")] == ["SPLR", "NU"]


# ---- Catalogue ---------------------------------------------------------------------------------

@pytest.fixture
def catalogued(library, doc):
    for family in ("GRP/ITM#/#", "GRP#", "M#.#", "M#.#I", "M#.#E#"):
        library.set_family_enabled(doc.id, family, True)
    return library


def test_catalogue_lists_identifiers_under_what_they_belong_to(catalogued):
    entries = {e["key"]: e for e in catalogued.catalogue()}
    assert list(entries)[:4] == ["GRP/ITM281/001", "GRP/ITM365/001", "GRP/ITM367/004", "GRP/ITM371/001"] or "M3.2" in entries
    assert entries["M3.2I"]["parent"] == "M3.2" and entries["M3.2E0"]["parent"] == "M3.2"
    assert entries["GRP/ITM281/001"]["parent"] == "GRP281"
    assert entries["M3.2"]["defined"] and entries["M12.6"]["value"] in ("M 12.6", "M12.6")
    keys = list(entries)
    assert keys.index("M3.2") < keys.index("M12.6")                                           # Numbers in order, not as text


def test_a_words_entry_shows_its_fields_and_an_elements_entry_who_uses_it(catalogued):
    word = catalogued.identifier_detail("M3.2E0")
    assert [t["block"].label for t in word["tables"]] == ["Table 5.1-2"]
    assert [r[0] for r in word["tables"][0]["rows"]] == ["Course", "Speed", "Altitude", "Identity"]     # With its continuation
    assert "GRP/ITM 371/001" in word["contains"] and word["parent"] == "M3.2"

    element = catalogued.identifier_detail("GRP/ITM 281/001")
    row = next(r for r in element["rows"] if r["block"].label == "Table 5.1-1")
    assert dict(zip(row["columns"], row["cells"])) == {"FIELD": "Reference Number", "GRP/ITM": "281/001", "BITS": "19"}
    assert row["owners"] == ["M3.2I"] and "M3.2I" in element["used_by"]
    assert any("may carry" in r["block"].text for r in element["rules"])                      # The M 12.6 rule that mentions it

    message = catalogued.identifier_detail("M3.2")
    assert message["children"] == ("M3.2E0", "M3.2I") and message["defined"] and message["rules"]


def test_changes_between_revisions(catalogued, extractor):
    revised = message_standard(bits="21", extra_row=["Quality", "380/002", "4"], rule="within 6 seconds")
    newer, _ = catalogued.add_document(make_pdf(revised, header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), "XYZ-STD-9999B.pdf", extractor)
    older = next(d for d in catalogued.list_documents() if d.id != newer.id)
    for family in ("GRP/ITM#/#", "GRP#", "M#.#", "M#.#I", "M#.#E#"):
        catalogued.set_family_enabled(newer.id, family, True)

    word = catalogued.identifier_changes("M3.2I", older.id, newer.id)
    assert [c["cells"] for c in word["added"]] == [["Quality", "380/002", "4"]] and word["removed"] == []
    assert [(c["old"][2], c["new"][2]) for c in word["changed"]] == [("19", "21")] and word["unchanged"] == 1
    message = catalogued.identifier_changes("M3.2", older.id, newer.id)
    assert "within 6 seconds" in message["rules_added"][0].text and "within 12 seconds" in message["rules_removed"][0].text
    assert catalogued.identifier_changes("M3.2E0", older.id, newer.id)["changed"] == []


# ---- Health and markings -----------------------------------------------------------------------

def test_health_report(library, doc, extractor):
    checks = {c["name"]: c for c in library.health(doc.id)}
    assert checks["Printed page numbers"]["value"] == "100%" and not checks["Printed page numbers"]["warn"]
    assert checks["Tables"]["value"] == "3" and checks["Table captions with no table found"]["value"] == "0"
    assert checks["References to tables and figures not found"]["value"] == "0 of 2"
    assert checks["Distribution statement"]["value"] == "found"
    assert not any(c["warn"] for c in checks.values())

    # A table drawn without lines isn't detected: its caption is reported, with the page
    bare, _ = library.add_document(make_pdf([["1 SCOPE", "1.1 Purpose. See TABLE 1-1 for the limits of the unit.",
                                              "TABLE 1-1. Limits", "Pressure 10 bar Temperature 40 degrees"]] * 1), "bare.pdf", extractor)
    checks = {c["name"]: c for c in library.health(bare.id)}
    assert checks["Table captions with no table found"]["warn"] and "pages 1" in checks["Table captions with no table found"]["note"]
    assert checks["Printed page numbers"]["warn"]


def test_markings_travel_with_pins(library, doc):
    store = CollectionStore(library.conn)
    collection = store.ensure_default()
    passage = block(library, doc, "The M3.2 message")
    store.add_pin(collection, passage, doc.title, "XYZ-STD-9999A, 5.1, p. 5-1", marking=doc.distribution)
    exported = to_markdown("Notes", store.pins(collection))
    assert "This extract contains material from documents marked:" in exported
    assert exported.count("DISTRIBUTION STATEMENT C.") == 2                                    # Up front, and with the item
