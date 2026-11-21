from __future__ import annotations

import argparse
import json
import logging
import sys
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
    if args.classes:
        update["classes_dir"] = args.classes
    return settings.model_copy(update=update)


def _with_cache(llm: LLM, args: argparse.Namespace, settings: Settings) -> LLM:
    if not getattr(args, "cache", None):
        return llm
    return DiskCachedLLM(llm, args.cache, model=settings.llm_model)


def _print_cache_stats(llm: LLM) -> None:
    if isinstance(llm, DiskCachedLLM):
        print("cache:", llm.stats())


def _write_summary(args, results, settings, llm) -> None:
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
                "output": rel.with_suffix(".json").as_posix()
                if rel and r.data is not None
                else None,
            }
        )
    summary = {
        "model": settings.llm_model,
        "mode": settings.extraction_mode,
        "files": files,
        **({"usage": usage.to_dict()} if usage else {}),
    }
    args.trace.mkdir(parents=True, exist_ok=True)
    (args.trace / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(
    argv: list[str] | None = None,
    llm: LLM | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    args = _parser().parse_args(argv)
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
    results = run_batch(
        args.input, args.output, args.trace, classes, llm, settings, workers=args.workers
    )
    _write_summary(args, results, settings, llm)
    errors = [r for r in results if r.error]
    unknown = [r for r in results if r.class_name == UNKNOWN and not r.error]
    print(
        f"Przetworzono {len(results)} plików: {len(results) - len(errors) - len(unknown)} "
        f"zapisanych, {len(unknown)} nieznanych, {len(errors)} błędów (tryb: {settings.extraction_mode})"
    )
    usage = getattr(llm, "usage", None)
    if usage:
        print("tokeny:", usage.to_dict())
    _print_cache_stats(llm)
    return 1 if errors else 0
