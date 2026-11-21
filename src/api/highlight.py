"""Lokalizacja cytatu w PDF-ie (prostokąty do podświetlenia) i renderowanie stron."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from rapidfuzz import fuzz

MIN_SCORE = 85
MAX_RECTS = 16


def _normalize(text: str) -> tuple[str, list[int]]:
    """Małe litery, ciągi białych znaków jako jedna spacja; zwraca też mapę na indeksy źródła."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(i)
        else:
            out.append(ch.lower()[0])
            index.append(i)
    return "".join(out).strip(), index


def page_count(pdf_bytes: bytes) -> int:
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(pdf)
    finally:
        pdf.close()


def locate_quotes(pdf_bytes: bytes, quotes: dict[str, str | None]) -> dict[str, list[dict]]:
    """Ścieżka pola → prostokąty `{page, x, y, w, h}` (ułamki strony, lewy górny róg).

    Dopasowanie przybliżone do tekstu strony; brak dopasowania lub brak warstwy tekstowej
    (skan) daje pustą listę.
    """
    wanted = {path: _normalize(q)[0] for path, q in quotes.items() if q and q.strip()}
    result: dict[str, list[dict]] = {path: [] for path in quotes}
    if not wanted:
        return result
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        best: dict[str, tuple[float, int, int, int]] = {}  # path -> (score, page, start, count)
        for pno in range(len(pdf)):
            textpage = pdf[pno].get_textpage()
            raw = textpage.get_text_range()
            norm, index = _normalize(raw)
            if not norm:
                continue
            for path, q in wanted.items():
                al = fuzz.partial_ratio_alignment(q, norm)
                if al is None or al.score < MIN_SCORE or al.dest_end <= al.dest_start:
                    continue
                if path not in best or al.score > best[path][0]:
                    start = index[al.dest_start]
                    end = index[al.dest_end - 1] + 1
                    best[path] = (al.score, pno, start, end - start)
        for path, (_, pno, start, count) in best.items():
            page = pdf[pno]
            width, height = page.get_size()
            textpage = page.get_textpage()
            n = textpage.count_rects(start, count)
            for i in range(min(n, MAX_RECTS)):
                left, bottom, right, top = textpage.get_rect(i)
                result[path].append(
                    {
                        "page": pno + 1,
                        "x": round(left / width, 5),
                        "y": round((height - top) / height, 5),
                        "w": round((right - left) / width, 5),
                        "h": round((top - bottom) / height, 5),
                    }
                )
    finally:
        pdf.close()
    return result


def render_page(pdf_bytes: bytes, number: int, width: int = 900) -> bytes:
    """PNG strony `number` (od 1) w szerokości `width` px."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        if not 1 <= number <= len(pdf):
            raise IndexError(number)
        page = pdf[number - 1]
        scale = max(width, 100) / page.get_size()[0]
        image = page.render(scale=scale).to_pil().convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
