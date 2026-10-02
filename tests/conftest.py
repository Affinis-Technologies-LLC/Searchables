"""
Shared fixtures. The tests use made-up PDFs (built here with PyMuPDF) and a stand-in for the
language model, so they need neither your documents nor the downloaded model.
"""
import os
import tempfile
import zlib
from pathlib import Path

# Before anything imports src.config: a throwaway library, and a models folder with no model in it
# (removed again when the tests end)
_TEMP = tempfile.TemporaryDirectory(prefix="searchables-tests-")
_ROOT = Path(_TEMP.name)
os.environ["SEARCHABLES_DATA_DIR"] = str(_ROOT / "data")
os.environ["SEARCHABLES_MODEL_DIR"] = str(_ROOT / "models")

import numpy as np
import pymupdf
import pytest

from src import config
from src.extractor.pdf import PDFExtractor
from src.search import semantic
from src.search.library import Library

DIMENSIONS = 256


def fake_vectors(texts):
    """Stand-in for the model: texts sharing words get similar vectors (hashed bag of words)."""
    out = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    for i, text in enumerate(texts):
        text = text.split(": ", 1)[-1] if text.startswith(("query: ", "passage: ")) else text
        for word in "".join(c if c.isalnum() else " " for c in text.lower()).split():
            out[i, zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
        norm = np.linalg.norm(out[i])
        if norm:
            out[i] /= norm
    return out


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Tests never load (or download) the real model; without the `model` fixture, meaning search is simply off."""
    def refuse():
        raise RuntimeError("The tests don't load the language model.")
    monkeypatch.setattr(semantic, "get_model", refuse)


@pytest.fixture
def model(monkeypatch):
    """Meaning search switched on, with the stand-in model. Records every batch of passages it reads."""
    read = []

    def embed_passages(texts, on_progress=None):
        read.append(list(texts))
        if on_progress:
            on_progress(len(texts), len(texts))
        return fake_vectors(texts)

    monkeypatch.setattr(config, "EMBEDDING_DIMENSIONS", DIMENSIONS)
    monkeypatch.setattr(semantic, "model_files_present", lambda: True)
    monkeypatch.setattr(semantic, "get_model", lambda: None)  # The app warms the model up when it starts
    monkeypatch.setattr(semantic, "embed_passages", embed_passages)
    monkeypatch.setattr(semantic, "embed_query", lambda text: fake_vectors([text])[0])
    monkeypatch.setattr(semantic, "embed_for_comparison", fake_vectors)
    semantic._sentence_cache.clear()
    return read


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "library.db", tmp_path / "pdfs")


@pytest.fixture
def extractor():
    return PDFExtractor(use_ocr=False)


def make_pdf(pages, header="ACME-STD-1234 Rev B", footers=None) -> bytes:
    """
    A PDF from `pages`: each a list of paragraphs (str), or tables as {"caption": str, "rows": [[cell, …], …]}
    drawn with ruled cells. Paragraphs are spaced apart so each becomes its own passage. `footers`
    gives each page's printed number ("4-1", "A-3"); otherwise "Page N of M".
    """
    doc = pymupdf.open()
    for number, items in enumerate(pages, 1):
        page = doc.new_page()
        page.insert_text((72, 40), header, fontsize=8)                         # Running header
        page.insert_text((290, 815), footers[number - 1] if footers else f"Page {number} of {len(pages)}", fontsize=8)
        y = 100
        for item in items:
            if isinstance(item, str):
                box = pymupdf.Rect(72, y, 520, y + 200)
                used = 200 - page.insert_textbox(box, item, fontsize=10)
                y += used + 16
                continue
            page.insert_text((72, y + 10), item["caption"], fontsize=10)
            y += 24
            rows = item["rows"]
            widths = [448 / len(rows[0])] * len(rows[0])
            height = 18
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    rect = pymupdf.Rect(72 + sum(widths[:c]), y + r * height, 72 + sum(widths[:c + 1]), y + (r + 1) * height)
                    page.draw_rect(rect, width=0.7)
                    page.insert_text((rect.x0 + 3, rect.y0 + 12), cell, fontsize=8)
            y += len(rows) * height + 20
    return doc.tobytes()


STANDARD = [
    [
        "1 SCOPE",
        "1.1 Purpose. This standard establishes the message requirements for the data terminal.",
        "2 APPLICABLE DOCUMENTS",
        "2.1 General. The documents listed in ISO 4126-1 form a part of this standard to the extent specified.",
        "3 DEFINITIONS",
        "4 GENERAL REQUIREMENTS",
        "4.1 Transmit rules",
        "The terminal shall perform the following when a item is dropped:",
        "a. Transmit a drop item report within 12 seconds.",
        "b. Cease reporting the item on the interface.",
        "The operator should review the item table weekly as described in Table 1.",
        "4.2 Calibration",
        "Calibration records shall be retained for a period of 5 years after the equipment is withdrawn.",
        "NOTE The retention period may be extended by the acquiring activity.",
    ],
    [
        "4.2.1.1.1.1.1 Deeply nested rules",
        "Message K3.5 shall be transmitted whenever FLD 2041 changes value, as given in Table 1.",
        {"caption": "TABLE 1. Message summary", "rows": [
            ["Message", "Field", "Purpose"],
            ["K3.5", "FLD 2041", "Item position update"],
            ["K3.6", "FLD 2042", "Item identity update"],
            ["K4.1", "FLD 2050", "Engagement status"],
        ]},
    ],
    [
        "APPENDIX A",
        "10. SCOPE",
        "10.1 Purpose. This appendix gives the pump lubrication schedule for the cooling unit.",
        "20. SCHEDULE",
        "20.1 Interval. The lubricant shall be replaced every 6 months or 500 hours.",
    ],
]


@pytest.fixture
def standard_pdf() -> bytes:
    return make_pdf(STANDARD)


def message_standard(bits="19", extra_row=None, rule="within 12 seconds"):
    """A small standard laid out the way military standards are: a message, its words as tables of fields, data elements."""
    word = [["FIELD", "GRP/ITM", "BITS"], ["Reference Number", "281/001", bits], ["Strength", "755/002", "4"]]
    if extra_row:
        word.append(extra_row)
    return [
        [
            "1 SCOPE",
            "1.1 Purpose. This standard defines the M-series messages. DISTRIBUTION STATEMENT C. Distribution "
            "authorized to U.S. Government agencies and their contractors.",
            "3 DEFINITIONS",
            "3.1 Acronyms and abbreviations",
            "SPLR Status, Position and Location Report\nRN Reference Number\nNU Network Unit",
        ],
        [
            "5 DETAILED REQUIREMENTS",
            "5.1 M3.2 Status message",
            f"The M3.2 message shall be transmitted {rule} of a item update. Its words are M3.2I and M3.2E0; "
            "see TABLE 5.1-1 and TABLE 5.1-2.",
            "GRP 281/ITM 001 is the reference number (RN) of the reported item, and GRP 755/ITM 002 its strength.",
            {"caption": "TABLE 5.1-1. M3.2I initial word", "rows": word},
            {"caption": "TABLE 5.1-2. M3.2E0 extension word", "rows": [
                ["FIELD", "GRP/ITM", "BITS"], ["Course", "371/001", "9"], ["Speed", "367/004", "11"]]},
        ],
        [
            {"caption": "TABLE 5.1-2. M3.2E0 extension word - Continued", "rows": [
                ["Altitude", "365/001", "13"], ["Identity", "376/007", "3"]]},
            "5.2 M 12.6 Summary message",
            "The M 12.6 message may carry GRP 281/ITM 001 when a NU reports its SPLR.",
        ],
    ]


MESSAGE_FOOTERS = ["1", "5-1", "5-2"]
