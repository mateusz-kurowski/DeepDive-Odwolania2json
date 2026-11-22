from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Mapping
from pathlib import Path

from src.classconfig import ClassConfigError, load_classes
from src.classify import UNKNOWN
from src.evaluate import evaluate
from src.llm import LLM, OpenAICompatLLM
from src.llmcache import DiskCachedLLM
from src.pipeline import find_pdfs, run_batch
from src.settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src", description="PDF-y spraw KIO → JSON zgodny ze schematem UZP"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--classes", type=Path, help="katalog z klasami YAML (domyślnie CLASSES_DIR)"
        )
        p.add_argument("--mode", choices=["hybrid", "llm_only"], help="nadpisuje EXTRACTION_MODE")
        p.add_argument("--workers", type=int, default=4)
        p.add_argument(
            "--doc-timeout",
            type=float,
            help="limit czasu na dokument w sekundach (nadpisuje DOC_TIMEOUT_S; 0 = bez limitu)",
        )
        p.add_argument(
            "--cache",
            type=Path,
            help="katalog cache odpowiedzi LLM na dysku (domyślnie wyłączony)",
        )

    run = sub.add_parser("run", help="przetwórz input/ do output/")
    run.add_argument("--input", type=Path, default=Path("input"))
    run.add_argument("--output", type=Path, default=Path("output"))
    run.add_argument("--trace", type=Path, default=Path("trace"))
    common(run)

    ev = sub.add_parser("eval", help="policz F1 na przykładach z referencją")
    ev.add_argument("--data", type=Path, default=Path("data/dane"))
    ev.add_argument("--model", help="nadpisuje LLM_MODEL")
    ev.add_argument("--limit", type=int)
    ev.add_argument(
        "--examples",
        help="tylko wybrane przykłady, po przecinku (np. 01,02,13 albo przyklad_01)",
    )
    ev.add_argument("--dump", type=Path, help="zapisz predykcje, referencje i różnice per dokument")
    ev.add_argument("--out-json", type=Path, help="zapisz raport jako JSON")
    common(ev)

    sw = sub.add_parser("sweep", help="seria ewaluacji na wariantach z pliku YAML")
    sw.add_argument("config", type=Path, help="plik YAML z wariantami (np. sweeps/przyklad.yaml)")

    serve = sub.add_parser("serve", help="uruchom API (wymaga: uv sync --extra api)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--web", type=Path, help="serwuj też statyczny front z tego katalogu")

    gui = sub.add_parser("gui", help="interfejs graficzny w przeglądarce, bez Dockera")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8080)
    gui.add_argument("--no-browser", action="store_true", help="nie otwieraj przeglądarki")

    sub.add_parser("check", help="sprawdź konfigurację (.env, klasy, połączenie z modelem)")

    classes = sub.add_parser("classes", help="wypisz wczytane klasy")
    classes.add_argument("--classes", type=Path)
    return parser


def _settings(args: argparse.Namespace, env: Mapping[str, str] | None) -> Settings:
    settings = Settings.from_env(env)
    update: dict = {}
    if getattr(args, "mode", None):
        update["extraction_mode"] = args.mode
    if getattr(args, "model", None):
        update["llm_model"] = args.model
    if getattr(args, "classes", None):
        update["classes_dir"] = args.classes
    if getattr(args, "doc_timeout", None) is not None:
        update["doc_timeout_s"] = args.doc_timeout
    return settings.model_copy(update=update)


def _with_cache(llm: LLM, args: argparse.Namespace, settings: Settings) -> LLM:
    if not getattr(args, "cache", None):
        return llm
    return DiskCachedLLM(llm, args.cache, model=settings.llm_model)


def _print_cache_stats(llm: LLM) -> None:
    if isinstance(llm, DiskCachedLLM):
        print("cache:", llm.stats())


def timing(results, wall_seconds: float) -> dict:
    """Czas przebiegu: ściana zegara i statystyki per dokument (do limitu 150 PDF / 45 min)."""
    per_doc = sorted(r.seconds for r in results)
    n = len(per_doc)
    slowest = max(results, key=lambda r: r.seconds, default=None)
    return {
        "wall_seconds": round(wall_seconds, 1),
        "docs": n,
        "wall_seconds_per_doc": round(wall_seconds / n, 2) if n else None,
        "doc_seconds_mean": round(sum(per_doc) / n, 2) if n else None,
        "doc_seconds_p95": round(per_doc[min(n - 1, int(0.95 * n))], 2) if n else None,
        "doc_seconds_max": round(per_doc[-1], 2) if n else None,
        "slowest": slowest.path.name if slowest and slowest.path else None,
        "read_seconds_total": round(sum(r.read_seconds for r in results), 1),
        "ocr_docs": sum(1 for r in results if r.ocr_used),
        "projected_150_pdf_minutes": round(wall_seconds / n * 150 / 60, 1) if n else None,
    }


def _write_summary(args, results, settings, llm, wall_seconds: float = 0.0) -> None:
    usage = getattr(llm, "usage", None)
    files = []
    for r in results:
        rel = r.path.relative_to(args.input) if r.path else None
        files.append(
            {
                "source": rel.as_posix() if rel else None,
                "class": r.class_name,
                "error": r.error,
                "ocr_used": r.ocr_used,
                "seconds": round(r.seconds, 2),
                "read_seconds": round(r.read_seconds, 2),
                "output": rel.with_suffix(".json").as_posix() if rel else None,
            }
        )
    summary = {
        "model": settings.llm_model,
        "mode": settings.extraction_mode,
        "workers": args.workers,
        "doc_timeout_s": settings.doc_timeout_s,
        "timing": timing(results, wall_seconds),
        "files": files,
        **({"usage": usage.to_dict()} if usage else {}),
    }
    args.trace.mkdir(parents=True, exist_ok=True)
    (args.trace / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _sweep(args: argparse.Namespace, llm: LLM | None, env: Mapping[str, str] | None) -> int:
    from src.sweep import SweepConfigError, run_sweep

    try:
        results = run_sweep(args.config, env=env, llm_factory=(lambda s: llm) if llm else None)
    except (SweepConfigError, ClassConfigError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 2
    for r in results:
        status = r["error"] or f"F1 {r['micro_f1']:.4f} ({r['docs']} dok.)"
        print(f"{r['name']} [{r['model']}]: {status}")
    return 1 if any(r["error"] for r in results) else 0


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "Brak zależności API. Zainstaluj: pip install -r requirements.txt "
            "(lub uv sync --extra api)",
            file=sys.stderr,
        )
        return 2
    web = WEB_DIR if args.command == "gui" else args.web
    if web:
        os.environ["WEB_DIR"] = str(Path(web).resolve())
    if args.command == "gui":
        url = f"http://{args.host}:{args.port}/"
        print(f"Interfejs: {url}  (Ctrl+C kończy)")
        if not args.no_browser:
            threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("src.api.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


def main(
    argv: list[str] | None = None,
    llm: LLM | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    args = _parser().parse_args(argv)
    if args.command == "sweep":
        return _sweep(args, llm, env)
    if args.command in ("serve", "gui"):
        return _serve(args)
    if args.command == "check":
        from src.check import run_check

        return run_check(_settings(args, env), env)
    settings = _settings(args, env)
    try:
        classes = load_classes(settings.classes_dir)
    except ClassConfigError as exc:
        print(f"Błąd konfiguracji klasy: {exc}", file=sys.stderr)
        return 2
    if not classes:
        print(
            f"Nie znaleziono klas w '{settings.classes_dir}' (oczekiwane pliki *.yaml). "
            "Sprawdź katalog roboczy, --classes lub CLASSES_DIR.",
            file=sys.stderr,
        )
        return 2

    if args.command == "classes":
        for name, cfg in classes.items():
            print(f"{name}: {cfg.description}")
        return 0

    if llm is None and not settings.llm_model:
        print("Brak nazwy modelu: ustaw LLM_MODEL (lub --model).", file=sys.stderr)
        return 2

    if args.command == "eval":
        llm = _with_cache(llm or OpenAICompatLLM(settings), args, settings)
        only = [x for x in args.examples.split(",") if x.strip()] if args.examples else None
        report = evaluate(
            args.data,
            classes,
            llm,
            settings,
            limit=args.limit,
            workers=args.workers,
            dump_dir=args.dump,
            only=only,
        )
        print(f"model: {settings.llm_model}, tryb: {settings.extraction_mode}")
        print(report.render())
        usage = getattr(llm, "usage", None)
        if usage:
            print("tokeny:", usage.to_dict())
        _print_cache_stats(llm)
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(
                json.dumps(
                    {
                        **report.to_dict(),
                        "model": settings.llm_model,
                        "mode": settings.extraction_mode,
                        **({"usage": usage.to_dict()} if usage else {}),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return 0

    if not find_pdfs(args.input):
        print(f"Brak plików PDF w {args.input}")
        return 0
    llm = _with_cache(llm or OpenAICompatLLM(settings), args, settings)
    start = time.perf_counter()
    results = run_batch(
        args.input, args.output, args.trace, classes, llm, settings, workers=args.workers
    )
    wall = time.perf_counter() - start
    _write_summary(args, results, settings, llm, wall)
    errors = [r for r in results if r.error]
    unknown = [r for r in results if r.class_name == UNKNOWN and not r.error]
    print(
        f"Przetworzono {len(results)} plików: {len(results) - len(errors) - len(unknown)} "
        f"zapisanych, {len(unknown)} nieznanych (pusty JSON), {len(errors)} błędów (tryb: {settings.extraction_mode})"
    )
    t = timing(results, wall)
    # Przy mniej niż 2 plikach na wątek równoległość nie działa i prognoza jest myląco wysoka.
    projection = (
        f"prognoza dla 150 PDF: {t['projected_150_pdf_minutes']} min (limit 45)"
        if len(results) >= 2 * args.workers
        else f"prognoza dla 150 PDF: za mało plików (potrzeba ≥{2 * args.workers})"
    )
    print(
        f"czas: {t['wall_seconds']} s ({t['wall_seconds_per_doc']} s/plik przy {args.workers} wątkach), "
        f"najwolniejszy: {t['slowest']} {t['doc_seconds_max']} s; {projection}"
    )
    usage = getattr(llm, "usage", None)
    if usage:
        print("tokeny:", usage.to_dict())
    _print_cache_stats(llm)
    return 1 if errors else 0
