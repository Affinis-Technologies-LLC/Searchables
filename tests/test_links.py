"""Fixing a PDF's dead links (ADR-031): the checker's states on a fixture broken the way a bad merge breaks links, and the fix."""
import pymupdf
import pytest

from src.extractor.pdf import PDFExtractor
from src.research.links import check, fixed
from tests.conftest import MESSAGE_FOOTERS, make_pdf, message_standard


def _link_xrefs(doc: pymupdf.Document, page_index: int):
    annots = doc.xref_get_key(doc[page_index].xref, "Annots")[1]
    return [int(part.split()[0]) for part in annots.strip("[]").split("R") if part.strip()]


def broken_pdf() -> bytes:
    """
    The fixture standard with, on page 2: a GoTo whose destination object is gone (over "TABLE 5.1-2"),
    a GoTo to the wrong page (over the caption of TABLE 5.1-1, pointing at page 1), a named destination
    nobody defines (over "M3.2E0", which is no reference), a healthy GoTo (over the caption of TABLE
    5.1-2) and a URI; bookmarks: "5.2 M 12.6 Summary message" whose destination object is gone, "5.1 M3.2 Status
    message" pointing at page 1 (the heading is on page 2), "Front matter" on page 1 (no such heading), and two
    healthy ones. "TABLE 5.1-1" in the sentence on page 2 carries no link at all.
    """
    doc = pymupdf.open("pdf", make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS))
    page = doc[1]
    t512 = page.search_for("TABLE 5.1-2")          # [0] in the sentence, [1] the caption
    t511 = page.search_for("TABLE 5.1-1")
    word = page.search_for("M3.2E0")[0]
    page.insert_link({"kind": pymupdf.LINK_GOTO, "from": t512[0], "page": 2, "to": pymupdf.Point(72, 72)})
    page.insert_link({"kind": pymupdf.LINK_GOTO, "from": t511[1], "page": 0, "to": pymupdf.Point(72, 72)})
    page.insert_link({"kind": pymupdf.LINK_GOTO, "from": word, "page": 0, "to": pymupdf.Point(72, 72)})
    page.insert_link({"kind": pymupdf.LINK_GOTO, "from": t512[1], "page": 1, "to": pymupdf.Point(72, 400)})
    page.insert_link({"kind": pymupdf.LINK_URI, "from": word + (0, 30, 0, 30), "uri": "https://example.invalid/old"})
    doc.set_toc([[1, "1 SCOPE", 1], [1, "Front matter", 1], [1, "5 DETAILED REQUIREMENTS", 2],
                 [2, "5.1 M3.2 Status message", 1], [2, "5.2 M 12.6 Summary message", 3]])
    dead, _, named, _, _ = _link_xrefs(doc, 1)
    doc.xref_set_key(dead, "A", "<</S/GoTo/D[999 0 R/XYZ 0 0 0]>>")       # The page object was dropped by a merge
    doc.xref_set_key(named, "A", "<</S/GoTo/D(lost-section)>>")           # A named destination nobody defines
    bookmark = doc.get_toc(simple=False)[4][3]["xref"]
    doc.xref_set_key(bookmark, "A", "<</S/GoTo/D[999 0 R/XYZ 0 0 0]>>")
    return doc.tobytes()


@pytest.fixture(scope="module")
def reader():
    return PDFExtractor(use_ocr=False)


@pytest.fixture(scope="module")
def report(reader):
    return check(broken_pdf(), "XYZ-STD-9999A.pdf", reader)


def test_the_fixture_is_broken_the_way_a_merge_breaks_links():
    doc = pymupdf.open("pdf", broken_pdf())
    assert doc.page_count == 3
    # PyMuPDF reports both the dead GoTo and the dead bookmark as page 1: the raw check is what finds them
    assert doc[1].get_links()[0]["page"] == 0 and doc.get_toc()[4][2] == 1
    assert doc.xref_get_key(doc[1].get_links()[0]["xref"], "A/D")[1].startswith("[999 0 R")


def test_every_link_gets_its_state(report):
    assert report.refused == "" and report.page_count == 3
    states = [(l.text, l.state, l.reference, l.proposed_page) for l in report.links[:4]]
    assert states == [
        ("TABLE 5.1-2", "dead", "Table 5.1-2", 2),
        ("TABLE 5.1-1", "wrong page", "Table 5.1-1", 2),
        ("M3.2E0", "unresolved", "", None),
        ("TABLE 5.1-2", "ok", "Table 5.1-2", None),
    ]
    assert (report.links[4].state, report.links[4].reference, report.links[4].proposed_page) == ("external", "", None)
    assert [l.page for l in report.links] == [2] * 5 and report.links[4].target == "https://example.invalid/old"
    assert report.links[0].target == "a page object that doesn't exist" and report.links[2].target == "named destination 'lost-section'"
    assert report.links[1].target == "page 1" and report.links[3].target == "page 2"
    assert report.counts == {"ok": 1, "dead": 1, "wrong page": 1, "unresolved": 1, "external": 1}


def test_bookmarks_and_unlinked_references(report):
    assert [(b.title, b.page, b.state, b.proposed_page) for b in report.bookmarks] == [
        ("1 SCOPE", 1, "ok", None), ("Front matter", 1, "unchecked", None), ("5 DETAILED REQUIREMENTS", 2, "ok", None),
        ("5.1 M3.2 Status message", 1, "wrong page", 2), ("5.2 M 12.6 Summary message", None, "dead", 3)]
    assert [(h.page, h.title) for h in report.unbookmarked] == [(1, "3 DEFINITIONS"), (1, "3.1 Acronyms and abbreviations")]
    assert [(u.page, u.reference, u.target_page) for u in report.unlinked] == [(2, "Table 5.1-1", 2)]


def test_the_fixed_file_checks_clean_and_keeps_every_page_s_text(report, reader):
    before = broken_pdf()
    after = fixed(before, report)
    doc_before, doc_after = pymupdf.open("pdf", before), pymupdf.open("pdf", after)
    assert [p.get_text() for p in doc_before] == [p.get_text() for p in doc_after]
    assert doc_after.get_toc() == [[1, "1 SCOPE", 1], [1, "Front matter", 1], [1, "5 DETAILED REQUIREMENTS", 2],
                                   [2, "5.1 M3.2 Status message", 2], [2, "5.2 M 12.6 Summary message", 3]]
    again = check(after, "XYZ-STD-9999A.pdf", reader)
    assert sorted(l.state for l in again.links) == ["external", "ok", "ok", "ok", "unresolved"]   # The unplaceable one is left alone
    assert all(l.target == "page 2" for l in again.links if l.state == "ok")
    assert [b.state for b in again.bookmarks] == ["ok", "unchecked", "ok", "ok", "ok"]
    # A skipped fix is not applied
    kept = check(fixed(before, report, skip={report.links[0].id}), "x.pdf", reader)
    assert sorted(l.state for l in kept.links) == ["dead", "external", "ok", "ok", "unresolved"]


def test_links_can_be_added_for_unlinked_references(report, reader):
    after = check(fixed(broken_pdf(), report, add=True), "x.pdf", reader)
    assert after.unlinked == [] and len(after.links) == 6
    added = after.links[-1]
    assert (added.page, added.text, added.state, added.target) == (2, "TABLE 5.1-1", "ok", "page 2")
    assert check(fixed(broken_pdf(), report), "x.pdf", reader).unlinked != []       # Off by default


def test_locked_signed_and_encrypted_files_are_refused(reader):
    plain = make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS)
    doc = pymupdf.open("pdf", plain)
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    assert "password" in check(locked, "x.pdf", reader).refused
    doc = pymupdf.open("pdf", plain)
    readonly = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", permissions=pymupdf.PDF_PERM_PRINT)
    assert "permissions" in check(readonly, "x.pdf", reader).refused
    doc = pymupdf.open("pdf", plain)
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", "<</SigFlags 3/Fields[]>>")
    assert "signed" in check(doc.tobytes(), "x.pdf", reader).refused
    with pytest.raises(ValueError):
        fixed(locked, check(locked, "x.pdf", reader))


def test_a_retitled_bookmark_and_the_outline_rebuilt_from_the_headings(reader):
    doc = pymupdf.open("pdf", make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS))
    doc.set_toc([[1, "1 SCOPE", 1], [1, "5 Detailed requirements (old title)", 2], [2, "5.1 Status message", 2]])
    source = doc.tobytes()
    report = check(source, "x.pdf", reader)
    # Matched by clause number: on the right page, so ok, with the heading's own text offered as the title
    assert [(b.state, b.proposed_title) for b in report.bookmarks] == [
        ("ok", None), ("ok", "5 DETAILED REQUIREMENTS"), ("ok", "5.1 M3.2 Status message")]
    assert pymupdf.open("pdf", fixed(source, report)).get_toc() == [[1, "1 SCOPE", 1], [1, "5 DETAILED REQUIREMENTS", 2], [2, "5.1 M3.2 Status message", 2]]
    # Rebuilt from the headings: every clause, levels from the numbers, each on its heading's page
    rebuilt = pymupdf.open("pdf", fixed(source, report, outline=True))
    assert rebuilt.get_toc() == [[1, "1 SCOPE", 1], [1, "3 DEFINITIONS", 1], [2, "3.1 Acronyms and abbreviations", 1],
                                 [1, "5 DETAILED REQUIREMENTS", 2], [2, "5.1 M3.2 Status message", 2], [2, "5.2 M 12.6 Summary message", 3]]
    again = check(rebuilt.tobytes(), "x.pdf", reader)
    assert all(b.state == "ok" for b in again.bookmarks) and again.unbookmarked == []
    assert [p.get_text() for p in pymupdf.open("pdf", source)] == [p.get_text() for p in rebuilt]


def test_the_library_reports_bookmarks_against_the_clauses(library, extractor):
    plain, _ = library.add_document(make_pdf(message_standard(), header="XYZ-STD-9999", footers=MESSAGE_FOOTERS), "plain.pdf", extractor)
    row = next(c for c in library.health(plain.id) if c["name"] == "Bookmarks")
    assert row["value"] == "none" and not row["warn"] and "Links view can add them from the 6 clauses found" in row["note"]
    broken, _ = library.add_document(broken_pdf(), "broken.pdf", extractor)
    row = next(c for c in library.health(broken.id) if c["name"] == "Bookmarks")
    assert row["value"] == "5 for 6 clauses" and row["warn"]
    assert "1 points at the wrong page" in row["note"] and "1 whose destination is gone" in row["note"] and "2 clauses have none" in row["note"]
