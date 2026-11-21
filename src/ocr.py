"""OCR skanów: model z wizją (VLM, domyślnie) lub Tesseract (opcjonalny, nie instaluje się domyślnie)."""

from __future__ import annotations

import base64
import io
import logging
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.settings import Settings

log = logging.getLogger(__name__)

OCR_SCALE = 2
JPEG_QUALITY = 85
MAX_OCR_PAGES = 50
MAX_PIXELS_PER_PAGE = 20_000_000
VLM_MAX_TOKENS = 4096
VLM_PROMPT = (
    "Przepisz dokładnie cały tekst widoczny na tej stronie dokumentu (język polski). "
    "Zachowaj kolejność, akapity, liczby, daty, numery kont i znaki interpunkcyjne bez zmian. "
    "Nie poprawiaj, nie tłumacz, nie streszczaj i nie dodawaj komentarzy: zwróć sam tekst."
)


class OcrUnavailable(Exception):
    """Wybrany backend OCR nie jest skonfigurowany lub zainstalowany."""


def render_pages(path: Path, scale: float = OCR_SCALE) -> Iterator[Any]:
    """Strony po jednej (generator). Limit stron i pikseli chroni przed PDF-ami-bombami."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        if len(document) > MAX_OCR_PAGES:
            raise OcrUnavailable(f"PDF ma {len(document)} stron (limit OCR: {MAX_OCR_PAGES})")
        for page in document:
            width, height = page.get_size()
            area = width * height * scale * scale
            page_scale = (
                scale
                if area <= MAX_PIXELS_PER_PAGE
                else scale * (MAX_PIXELS_PER_PAGE / area) ** 0.5
            )
            yield page.render(scale=page_scale).to_pil()
    finally:
        document.close()


def _data_uri(image: Any) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _vlm_client(settings: Settings) -> Any:
    import openai

    return openai.OpenAI(
        api_key=settings.vlm_api_key or settings.openai_api_key or "none",
        base_url=settings.vlm_base_url or settings.openai_base_url,
        timeout=180,
        max_retries=2,
    )


def vlm_ocr(path: Path, settings: Settings, client: Any = None) -> str:
    """Każda strona jako obraz do modelu z wizją (API zgodne z OpenAI); zwraca tekst stron."""
    if not settings.vlm_model:
        raise OcrUnavailable("Ustaw VLM_MODEL (nazwa modelu z wizją w LiteLLM/vLLM/Ollama)")
    client = client or _vlm_client(settings)
    parts = []
    for number, image in enumerate(render_pages(path), start=1):
        response = client.chat.completions.create(
            model=settings.vlm_model,
            temperature=0,
            max_tokens=VLM_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VLM_PROMPT},
                        {"type": "image_url", "image_url": {"url": _data_uri(image)}},
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise OcrUnavailable(f"Odpowiedź VLM pusta dla strony {number} ({path.name})")
        parts.append(text)
    return "\n".join(parts)


def tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def tesseract_ocr(path: Path) -> str:
    import pytesseract

    return "\n".join(pytesseract.image_to_string(image, lang="pol") for image in render_pages(path))


def ocr_pdf(path: Path, settings: Settings, client: Any = None) -> str:
    path = Path(path)
    if settings.ocr_backend == "tesseract":
        return _tesseract_or_explain(path)
    try:
        return vlm_ocr(path, settings, client=client)
    except Exception as exc:
        if not tesseract_available():
            raise
        log.warning("OCR przez VLM nieudany (%s), używam Tesseracta: %s", exc, path.name)
        return tesseract_ocr(path)


def _tesseract_or_explain(path: Path) -> str:
    if not tesseract_available():
        raise OcrUnavailable(
            "Tesseract nie jest zainstalowany (opcjonalny); instrukcja w README, sekcja OCR"
        )
    return tesseract_ocr(path)
