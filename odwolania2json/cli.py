from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path

from odwolania2json.classconfig import load_classes
from odwolania2json.classify import UNKNOWN
from odwolania2json.evaluate import evaluate
from odwolania2json.llm import LLM, OpenAICompatLLM
from odwolania2json.pipeline import find_pdfs, run_batch
from odwolania2json.settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odwolania2json", description="PDF-y spraw KIO → JSON zgodny ze schematem UZP"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--classes", type=Path, help="katalog z klasami YAML (domyślnie CLASSES_DIR)")
        p.add_argument("--mode", choices=["hybrid", "llm_only"], help="nadpisuje EXTRACTION_MODE")
        p.add_argument("--workers", type=int, default=4)

    run = sub.add_parser("run", help="przetwórz input/ do output/")
    run.add_argument("--input", type=Path, default=Path("input"))
    run.add_argument("--output", type=Path, default=Path("output"))
    run.add_argument("--trace", type=Path, default=Path("trace"))
    common(run)

    ev = sub.add_parser("eval", help="policz F1 na przykładach z referencją")
    ev.add_argument("--data", type=Path, default=Path("data/dane"))
    ev.add_argument("--model", help="nadpisuje LLM_MODEL")
    ev.add_argument("--limit", type=int)
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


def main(
    argv: list[str] | None = None,
    llm: LLM | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    args = _parser().parse_args(argv)
    settings = _settings(args, env)
    classes = load_classes(settings.classes_dir)

    if args.command == "classes":
        for name, cfg in classes.items():
            print(f"{name}: {cfg.description}")
        return 0

    if args.command == "eval":
        report = evaluate(
            args.data, classes, llm or OpenAICompatLLM(settings), settings,
            limit=args.limit, workers=args.workers,
        )
        print(f"model: {settings.llm_model}, tryb: {settings.extraction_mode}")
        print(report.render())
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        return 0

    if not find_pdfs(args.input):
        print(f"Brak plików PDF w {args.input}")
        return 0
    llm = llm or OpenAICompatLLM(settings)
    results = run_batch(
        args.input, args.output, args.trace, classes, llm, settings, workers=args.workers
    )
    errors = [r for r in results if r.error]
    unknown = [r for r in results if r.class_name == UNKNOWN and not r.error]
    print(
        f"Przetworzono {len(results)} plików: {len(results) - len(errors) - len(unknown)} "
        f"zapisanych, {len(unknown)} nieznanych, {len(errors)} błędów (tryb: {settings.extraction_mode})"
    )
    return 1 if errors else 0
