"""`python -m src check`: szybka diagnostyka przed pierwszym `run` (dla jury i nowych osób).

Sprawdza .env, klasy YAML, katalogi input/output i odpowiedź każdego modelu (1 token).
Kod wyjścia 0 = wszystko gotowe, 1 = coś wymaga poprawki (opis w wypisanej liście).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.classconfig import ClassConfigError, load_classes
from src.pipeline import find_pdfs
from src.settings import Settings

OK, WARN, FAIL = "OK   ", "UWAGA", "BŁĄD "


def _default_client(base_url: str, api_key: str) -> Any:
    import openai

    return openai.OpenAI(api_key=api_key or "none", base_url=base_url, timeout=30, max_retries=0)


def _ping(client: Any, model: str) -> str | None:
    """None = model odpowiada; inaczej krótki opis błędu."""
    try:
        client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
    except Exception as exc:  # noqa: BLE001 - każdy błąd API raportujemy tekstem
        return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    return None


def run_check(
    settings: Settings,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[str, str], Any] = _default_client,
    root: Path = Path("."),
) -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    rows: list[tuple[str, str, str]] = []

    def add(status: str, what: str, detail: str = "") -> None:
        rows.append((status, what, detail))

    if env is None:
        if (root / ".env").is_file():
            add(OK, ".env", "znaleziony")
        elif settings.openai_api_key:
            # Docker: plik .env zostaje na hoście, compose przekazuje zmienne do kontenera.
            add(OK, ".env", "brak pliku, konfiguracja ze zmiennych środowiska")
        else:
            add(FAIL, ".env", "brak pliku: cp .env.example .env i wklej klucz API")

    add(
        *(OK, "OPENAI_API_KEY", "ustawiony")
        if settings.openai_api_key
        else (FAIL, "OPENAI_API_KEY", "pusty")
    )
    add(OK, "OPENAI_BASE_URL", settings.openai_base_url)
    if not settings.llm_model:
        add(FAIL, "LLM_MODEL", "pusty")
    if settings.ocr_backend == "vlm" and not settings.vlm_model:
        add(WARN, "VLM_MODEL", "pusty: skany (PDF bez tekstu) nie zostaną odczytane")

    try:
        classes = load_classes(settings.classes_dir)
        if classes:
            add(OK, "klasy dokumentów", ", ".join(classes))
        else:
            add(FAIL, "klasy dokumentów", f"brak plików *.yaml w {settings.classes_dir}")
    except ClassConfigError as exc:
        add(FAIL, "klasy dokumentów", str(exc))

    for name in ("input", "output"):
        if not (root / name).is_dir():
            add(WARN, f"katalog {name}/", "nie istnieje (zostanie utworzony przy run)")
    pdfs = find_pdfs(root / "input") if (root / "input").is_dir() else []
    if pdfs:
        add(OK, "input/", f"{len(pdfs)} PDF")
    else:
        add(WARN, "input/", "brak PDF; przykład: skopiuj data/szablon-aplikacja/input/* do input/")

    if settings.openai_api_key or settings.llm_model:
        main_client = client_factory(settings.openai_base_url, settings.openai_api_key)
        vlm_client = (
            client_factory(settings.vlm_base_url, settings.vlm_api_key or settings.openai_api_key)
            if settings.vlm_base_url
            else main_client
        )
        for model in settings.models_used():
            is_vlm_only = model == settings.vlm_model and model not in (
                settings.model_for("classification"),
                settings.model_for("extraction"),
            )
            err = _ping(vlm_client if is_vlm_only else main_client, model)
            add(
                *(OK, f"model {model}", "odpowiada")
                if err is None
                else (FAIL, f"model {model}", err)
            )

    width = max(len(r[1]) for r in rows)
    for status, what, detail in rows:
        print(f"[{status}] {what.ljust(width)}  {detail}")
    failed = any(r[0] == FAIL for r in rows)
    print(
        "\nGotowe do uruchomienia: python -m src run"
        if not failed
        else "\nPopraw pozycje oznaczone BŁĄD (opis obok)."
    )
    return 1 if failed else 0
