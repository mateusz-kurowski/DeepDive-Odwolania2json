from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 50
MIN_TEXT_RATIO = 0.6
_PUNCT = set(".,;:()-/%§„”\"'!?–—")
OCR_SCALE = 2


@dataclass
class DocText:
    text: str
    pages: int
    ocr_used: bool


def looks_garbage(text: str, pages: int) -> bool:
    chars = [c for c in text if not c.isspace()]
    if not chars or len(chars) / max(pages, 1) < MIN_CHARS_PER_PAGE:
        return True
    good = sum(1 for c in chars if c.isalnum() or c in _PUNCT)
    return good / len(chars) < MIN_TEXT_RATIO


def _ocr(path: Path) -> str:
    import pypdfium2 as pdfium
    import pytesseract

    document = pdfium.PdfDocument(str(path))
    parts = []
    for page in document:
        image = page.render(scale=OCR_SCALE).to_pil()
        parts.append(pytesseract.image_to_string(image, lang="pol"))
    return "\n".join(parts)


def read_pdf(path: Path) -> DocText:
    path = Path(path)
    try:
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        log.warning("Nie można odczytać PDF %s: %s", path, exc)
        return DocText(text="", pages=0, ocr_used=False)

    if not looks_garbage(text, pages):
        return DocText(text=text, pages=pages, ocr_used=False)

    try:
        ocr_text = _ocr(path)
    except Exception as exc:
        log.warning("OCR nieudany dla %s: %s", path, exc)
        return DocText(text="", pages=pages, ocr_used=False)
    if looks_garbage(ocr_text, pages):
        log.warning("Brak czytelnego tekstu w %s (także po OCR)", path)
        return DocText(text="", pages=pages, ocr_used=True)
    return DocText(text=ocr_text, pages=pages, ocr_used=True)
