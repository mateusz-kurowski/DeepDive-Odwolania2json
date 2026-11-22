"""Seria ewaluacji na wielu wariantach ustawień (np. modele) z jednego pliku YAML.

Klucz API i adres są wspólne (env), wariant zmienia model, tryb, OCR itd.
Pełne wyniki każdego wariantu: <out_dir>/<nazwa>/{report.json,dump/}, zbiorczo:
<out_dir>/summary.{json,md}.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from src.classconfig import load_classes
from src.evaluate import evaluate
from src.llm import LLM, OpenAICompatLLM
from src.llmcache import DiskCachedLLM
from src.models import average_params, load_model_sizes, size_points
from src.settings import Settings

log = logging.getLogger(__name__)

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SweepConfigError(ValueError):
    pass


class _Common(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["hybrid", "llm_only"] | None = None
    ocr_backend: Literal["vlm", "tesseract"] | None = None
    vlm_model: str | None = None
    llm_config: Path | None = None
    classify_model: str | None = None
    extract_model: str | None = None
    data: Path | None = None
    limit: int | None = None
    examples: list[str] | None = None


class Variant(_Common):
    name: str
    model: str


class SweepConfig(_Common):
    out_dir: Path
    workers: int = 4
    cache: Path | None = None
    classes: Path | None = None
    variants: list[Variant]


def load_sweep(path: Path) -> SweepConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cfg = SweepConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise SweepConfigError(f"Zły plik konfiguracji serii '{path}': {exc}") from exc
    if not cfg.variants:
        raise SweepConfigError("Brak wariantów: dodaj listę 'variants'.")
    seen: set[str] = set()
    for v in cfg.variants:
        if not _NAME.match(v.name):
            raise SweepConfigError(f"Niepoprawna nazwa wariantu '{v.name}' (litery, cyfry, . _ -).")
        if v.name in seen:
            raise SweepConfigError(f"Nazwa wariantu '{v.name}' się powtarza.")
        seen.add(v.name)
    return cfg


def _pick(variant: Variant, cfg: SweepConfig, field: str):
    value = getattr(variant, field)
    return value if value is not None else getattr(cfg, field)


def _run_variant(
    variant: Variant,
    cfg: SweepConfig,
    base: Settings,
    classes: dict,
    llm_factory: Callable[[Settings], LLM],
) -> dict:
    update: dict = {"llm_model": variant.model}
    for src_field, dst in (
        ("mode", "extraction_mode"),
        ("ocr_backend", "ocr_backend"),
        ("vlm_model", "vlm_model"),
        ("llm_config", "llm_config"),
        ("classify_model", "classify_model"),
        ("extract_model", "extract_model"),
    ):
        value = _pick(variant, cfg, src_field)
        if value is not None:
            update[dst] = value
    settings = base.model_copy(update=update)
    llm = llm_factory(settings)
    if cfg.cache:
        llm = DiskCachedLLM(llm, cfg.cache, model=settings.llm_model)
    out = cfg.out_dir / variant.name
    report = evaluate(
        _pick(variant, cfg, "data") or Path("data/dane"),
        classes,
        llm,
        settings,
        limit=_pick(variant, cfg, "limit"),
        workers=cfg.workers,
        dump_dir=out / "dump",
        only=_pick(variant, cfg, "examples"),
    )
    usage = getattr(llm, "usage", None)
    payload = {
        **report.to_dict(),
        "model": settings.llm_model,
        "mode": settings.extraction_mode,
        "ocr_backend": settings.ocr_backend,
        "vlm_model": settings.vlm_model,
        **({"usage": usage.to_dict()} if usage else {}),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "report.txt").write_text(report.render() + "\n", encoding="utf-8")
    avg = average_params(settings.models_used(), load_model_sizes())
    return {
        "models_used": settings.models_used(),
        "avg_params_b": avg,
        "size_points": size_points(avg),
        "micro_f1": payload["micro_f1"],
        "precision": payload["precision"],
        "recall": payload["recall"],
        "docs": payload["docs"],
        "errors": payload["errors"],
        "citation_ok_rate": payload["citation_ok_rate"],
        "mode": settings.extraction_mode,
        "usage": payload.get("usage"),
    }


def _fmt(value) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "-"


def _markdown(results: list[dict]) -> str:
    lines = [
        "| wariant | model | tryb | F1 | P | R | dok. | błędy | cytaty OK | śr. mld param. | pkt rozmiaru | uwagi |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | {' + '.join(r.get('models_used') or [r['model']])} | {r.get('mode') or '-'} | {_fmt(r.get('micro_f1'))} "
            f"| {_fmt(r.get('precision'))} | {_fmt(r.get('recall'))} | {r.get('docs', '-')} "
            f"| {r.get('errors', '-')} | {_fmt(r.get('citation_ok_rate'))} "
            f"| {r.get('avg_params_b') if r.get('avg_params_b') is not None else '-'} "
            f"| {r.get('size_points') if r.get('size_points') is not None else '-'} "
            f"| {(r['error'] or '').splitlines()[0][:80] if r['error'] else ''} |"
        )
    return "\n".join(lines) + "\n"


def run_sweep(
    config_path: Path,
    env: Mapping[str, str] | None = None,
    llm_factory: Callable[[Settings], LLM] | None = None,
) -> list[dict]:
    cfg = load_sweep(config_path)
    base = Settings.from_env(env)
    classes_dir = cfg.classes or base.classes_dir
    classes = load_classes(classes_dir)
    factory = llm_factory or OpenAICompatLLM
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_path, cfg.out_dir / "sweep.yaml")
    results: list[dict] = []
    for variant in cfg.variants:
        log.info("wariant %s (model %s)", variant.name, variant.model)
        row = {"name": variant.name, "model": variant.model, "error": None}
        try:
            row.update(_run_variant(variant, cfg, base, classes, factory))
        except Exception as exc:  # jeden zły wariant nie przerywa serii
            log.error("wariant %s: %s", variant.name, traceback.format_exc())
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
        (cfg.out_dir / "summary.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (cfg.out_dir / "summary.md").write_text(_markdown(results), encoding="utf-8")
    return results
