"""The fixed rules: quantities and assessment, clause numbering, provisions, query building, comparison."""
from src.extractor.provisions import classify_provision, inherit_list_provisions
from src.extractor.structure import HeadingDetector
from src.models import TextBlock
from src.research.assess import assess, quantities
from src.research.compare import compare
from src.search import semantic
from src.search.query import build_fts_query


def labels(findings):
    return [(f.label, f.detail) for f in findings]


def test_quantities_read_percentages_and_one_spelling_per_number():
    assert quantities("shall not exceed 12% of the total") == {"%": {"12"}}
    assert quantities("12 % of range") == {"%": {"12"}}
    assert quantities("within 12.0 s") == quantities("within 12 s") == {"s": {"12"}}
    assert quantities("1,000 m and 1,5 kg") == {"m": {"1000"}, "kg": {"1.5"}}


def test_quantities_ignore_words_that_only_look_like_units():
    assert quantities("at least 3 in each group") == {}
    assert quantities("Table 5 a summary") == {}
    assert quantities("rated 5 A at 3 inches") == {"A": {"5"}, "in": {"3"}}


def test_assess_values_strength_and_conflict():
    pair = lambda a, b: [(a, b, 0.95)]
    assert labels(assess(pair("The error shall not exceed 12% of range.", "The error shall not exceed 15% of range."))[0]) \
        == [("Different value", "12% → 15%")]
    assert assess(pair("Report at least 3 in each group.", "Report at least 5 in each group."))[0] == []
    assert labels(assess(pair("Records shall be kept for 12 months.", "Records should be kept for 12 months."))[0]) \
        == [("Weaker requirement", "shall → should")]
    assert assess(pair("The valve shall be opened.", "The valve shall not be opened."))[0][0].label == "Possible conflict"


def test_assess_uses_a_list_items_inherited_provision():
    pairs = [("Transmit a drop item report.", "The terminal should transmit a drop item report.", 0.95)]
    assert assess(pairs)[0] == []
    assert labels(assess(pairs, focus_provision="requirement")[0]) == [("Weaker requirement", "shall → should")]


def headings(lines):
    detector, found = HeadingDetector([]), []
    for line in lines:
        heading, _ = detector.feed(1, line)
        found.append((heading.num if heading else None, detector.path))
    return found


def test_deep_clause_numbers_are_headings():
    found = headings(["1 SCOPE", "1.1 General", "1.1.2.3.4.5.6 Seven levels", "1.1.2.3.4.5.6.7.8.9 Ten levels"])
    assert [num for num, _ in found] == ["1", "1.1", "1.1.2.3.4.5.6", "1.1.2.3.4.5.6.7.8.9"]


def test_appendix_sections_numbered_in_tens_stay_under_their_appendix():
    found = headings(["1 SCOPE", "APPENDIX A", "10. SCOPE", "10.1 Purpose", "20. APPLICABLE DOCUMENTS",
                      "25. Not a section", "APPENDIX B", "10. SCOPE", "B.1 Detail"])
    assert [num for num, _ in found] == ["1", "Appendix A", "10", "10.1", "20", None, "Appendix B", "10", "B.1"]
    assert found[3][1] == "Appendix A › 10 SCOPE › 10.1 Purpose"
    assert found[7][1] == "Appendix B › 10 SCOPE"


def test_numbers_that_are_not_clauses_are_rejected():
    assert [num for num, _ in headings(["1 SCOPE", "12 widgets per box", "10. SCOPE"])] == ["1", None, None]


def block(i, text, kind="text"):
    return TextBlock(id=i, page=1, text=text, word_count=len(text.split()), kind=kind,
                     provision="" if kind != "text" else classify_provision(text))


def test_list_items_inherit_the_lead_ins_provision():
    blocks = inherit_list_provisions([
        block(0, "The terminal shall perform the following:"),
        block(1, "a. Transmit a drop item report."),
        block(2, "(2) Cease reporting; the operator may override this."),
        block(3, "• Retain the reference number."),
        block(4, "The display is described in the next clause."),
        block(5, "a. Not part of any list."),
        block(6, "Background: the following apply."),
        block(7, "a. No provision to inherit."),
    ])
    assert [b.provision for b in blocks] == ["requirement", "requirement", "permission", "requirement", "", "", "", ""]


def test_query_building():
    assert build_fts_query('calibration records') == '"calibration" "records"'
    assert build_fts_query('"shall not exceed" valve -relief') == '("shall not exceed" "valve") NOT ("relief")'
    assert build_fts_query('pump OR compressor') == '"pump" OR "compressor"'
    assert build_fts_query('calib*') == '"calib" *'
    assert build_fts_query('...') is None


def test_any_word_query_drops_filler_words():
    assert build_fts_query("how long must calibration records be kept", any_word=True) \
        == '"long" OR "must" OR "calibration" OR "records" OR "kept"'
    assert build_fts_query("what is it", any_word=True) == '"what" OR "is" OR "it"'  # Nothing else to search for


def test_table_chunks(monkeypatch):
    monkeypatch.setattr(semantic.config, "EMBEDDING_TABLE_CHARS", 120)
    rows = [[f"K{i}.1", f"Purpose of message number {i}"] for i in range(1, 11)]
    chunks = semantic.table_chunks("Table 1. Messages", ["Message", "Purpose"], rows)
    assert chunks[0][0] == 1 and chunks[-1][1] == 10
    assert all(a[1] + 1 == b[0] for a, b in zip(chunks, chunks[1:]))            # Every row, once, in order
    assert all(text.startswith("Table 1. Messages. Message | Purpose\n") for _, _, text in chunks)
    assert semantic.table_chunks("T", ["A", "B"], [["1", "2"]]) == []            # Fits in one: nothing extra


def clause(i, num, title, text):
    return [TextBlock(id=i * 2, page=1, text=f"{num} {title}", word_count=2, kind="heading", clause_num=num, clause_title=title),
            TextBlock(id=i * 2 + 1, page=1, text=text, word_count=len(text.split()), clause_num=num, clause_title=title)]


def test_compare_finds_renumbered_changed_added_and_removed_clauses():
    old = (clause(0, "1", "Scope", "This standard covers pumps.")
           + clause(1, "2", "Testing", "Each pump shall be tested at the rated pressure for ten minutes before delivery.")
           + clause(2, "3", "Marking", "Each pump shall be marked with the maker's name."))
    new = (clause(0, "1", "Scope", "This standard covers pumps and compressors.")
           + clause(1, "2", "Safety", "Guards shall be fitted over all rotating parts.")
           + clause(2, "3", "Pressure tests", "Each pump shall be tested at the rated pressure for fifteen minutes before delivery."))
    diffs = {(d.new or d.old).title: d for d in compare(old, new)}
    assert diffs["Scope"].status == "changed" and not diffs["Scope"].renumbered
    assert diffs["Safety"].status == "added"
    assert diffs["Pressure tests"].renumbered and diffs["Pressure tests"].old.num == "2"
    assert diffs["Marking"].status == "removed"
