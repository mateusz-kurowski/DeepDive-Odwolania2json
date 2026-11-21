import shutil
from pathlib import Path

import pytest

from odwolania2json import textextract
from odwolania2json.textextract import looks_garbage, read_pdf

ROOT = Path(__file__).resolve().parent.parent
TEXT_PDF = ROOT / "data/szablon-aplikacja/input/case1/negatywny przyklad.pdf"
SCAN_PDF = ROOT / "data/szablon-aplikacja/input/case1/przyklad odwolanie.pdf"


def test_text_pdf_read():
    doc = read_pdf(TEXT_PDF)
    assert "Procedura konkurencyjna" in doc.text
    assert doc.pages == 9
    assert doc.ocr_used is False


def test_looks_garbage_empty_and_symbols():
    assert looks_garbage("", 3)
    assert looks_garbage("   \n ", 1)
    assert looks_garbage("@#$%^&*~|<>" * 20, 1)
    assert not looks_garbage("Odwołanie wykonawcy od czynności zamawiającego. " * 10, 1)


def test_ocr_failure_returns_empty(monkeypatch):
    def boom(path):
        raise RuntimeError("tesseract not installed")

    monkeypatch.setattr(textextract, "_ocr", boom)
    doc = read_pdf(SCAN_PDF)
    assert doc.text == ""
    assert doc.ocr_used is False
    assert doc.pages == 7


def test_ocr_used_when_no_text_layer(monkeypatch):
    monkeypatch.setattr(textextract, "_ocr", lambda path: "Odwołanie " * 100)
    doc = read_pdf(SCAN_PDF)
    assert doc.ocr_used is True
    assert doc.text.startswith("Odwołanie")


def test_corrupt_pdf_returns_empty(tmp_path):
    bad = tmp_path / "zepsuty.pdf"
    bad.write_bytes(b"to nie jest pdf")
    doc = read_pdf(bad)
    assert doc.text == ""
    assert doc.pages == 0


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="brak Tesseracta")
def test_real_ocr_on_scanned_pdf():
    doc = read_pdf(SCAN_PDF)
    assert doc.ocr_used is True
    assert "Krajowej Izby Odwoławczej" in doc.text
