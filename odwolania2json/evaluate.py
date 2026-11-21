from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from odwolania2json.classconfig import ClassConfig, FieldSpec
from odwolania2json.llm import LLM
from odwolania2json.pipeline import process_pdf
from odwolania2json.settings import Settings
from odwolania2json.validators import date as normalize_date

log = logging.getLogger(__name__)


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    wrong: int = 0  # wartość niepusta po obu stronach, ale różna (liczona też w fp i fn)
    nulled: int = 0  # predykcja pusta, referencja z wartością (liczona też w fn)

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.tp + other.tp,
            self.fp + other.fp,
            self.fn + other.fn,
            self.wrong + other.wrong,
            self.nulled + other.nulled,
        )

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _norm(value: Any, spec: FieldSpec) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if spec.validator == "date":
        try:
            return normalize_date(text)
        except ValueError:
            pass
    return text.casefold()


def _lookup(item: dict, dotted: str) -> Any:
    node: Any = item
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _item_label(item: dict, spec: FieldSpec, index: int) -> str:
    for key in spec.key:
        value = _lookup(item, key)
        if value not in (None, ""):
            norm = _norm(value, FieldSpec(name=key, type="text"))
            return f"{key}={norm}"
    return str(index)


def _flatten(data: dict, fields: list[FieldSpec], prefix: str, out: dict[str, Any]) -> None:
    for spec in fields:
        value = data.get(spec.name) if isinstance(data, dict) else None
        path = f"{prefix}{spec.name}"
        if spec.type == "object":
            _flatten(value or {}, spec.fields, f"{path}.", out)
        elif spec.type == "array":
            for i, item in enumerate(value or []):
                _flatten(item, spec.fields, f"{path}[{_item_label(item, spec, i)}].", out)
        else:
            out[path] = _norm(value, spec)


def flatten(data: dict, cfg: ClassConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _flatten(data or {}, cfg.fields, "", out)
    return out


def _schema_path(path: str) -> str:
    return re.sub(r"\[[^\]]*\]", "[]", path)


def score_document(
    pred: dict | None, ref: dict, cfg: ClassConfig
) -> dict[str, Counts]:
    pred_flat = flatten(pred, cfg) if pred is not None else {}
    ref_flat = flatten(ref, cfg)
    result: dict[str, Counts] = {}
    for path in sorted(set(pred_flat) | set(ref_flat)):
        p, r = pred_flat.get(path), ref_flat.get(path)
        if p is None and r is None:
            continue
        c = Counts()
        if p is not None and p == r:
            c.tp = 1
        elif p is not None and r is not None:
            c.fp = c.fn = c.wrong = 1
        elif p is None:
            c.fn = c.nulled = 1
        else:
            c.fp = 1
        key = _schema_path(path)
        result[key] = result.get(key, Counts()) + c
    return result


@dataclass
class Report:
    per_field: dict[str, Counts] = field(default_factory=dict)
    docs: int = 0
    doc_exact: int = 0
    classified_ok: int = 0
    classified_total: int = 0
    cited_ok: int = 0
    cited_total: int = 0

    def add_counts(self, counts: dict[str, Counts]) -> None:
        for key, c in counts.items():
            self.per_field[key] = self.per_field.get(key, Counts()) + c

    def add_document(self, counts: dict[str, Counts]) -> None:
        self.add_counts(counts)
        self.docs += 1
        if all(c.fp == 0 and c.fn == 0 for c in counts.values()):
            self.doc_exact += 1

    def merge(self, other: Report) -> None:
        self.add_counts(other.per_field)
        for name in ("docs", "doc_exact", "classified_ok", "classified_total", "cited_ok", "cited_total"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def totals(self) -> Counts:
        out = Counts()
        for c in self.per_field.values():
            out = out + c
        return out

    @property
    def tp_total(self) -> int:
        return self.totals.tp

    @property
    def fp_total(self) -> int:
        return self.totals.fp

    @property
    def fn_total(self) -> int:
        return self.totals.fn

    @property
    def precision(self) -> float:
        return self.totals.precision

    @property
    def recall(self) -> float:
        return self.totals.recall

    @property
    def micro_f1(self) -> float:
        return self.totals.f1

    @property
    def doc_exact_match(self) -> float:
        return self.doc_exact / self.docs if self.docs else 0.0

    @property
    def classification_accuracy(self) -> float:
        return self.classified_ok / self.classified_total if self.classified_total else 0.0

    @property
    def citation_ok_rate(self) -> float:
        return self.cited_ok / self.cited_total if self.cited_total else 0.0

    @property
    def null_rate_on_ref_valued(self) -> float:
        t = self.totals
        valued = t.tp + t.wrong + t.nulled
        return t.nulled / valued if valued else 0.0

    def to_dict(self) -> dict:
        return {
            "docs": self.docs,
            "micro_f1": self.micro_f1,
            "precision": self.precision,
            "recall": self.recall,
            "doc_exact_match": self.doc_exact_match,
            "classification_accuracy": self.classification_accuracy,
            "citation_ok_rate": self.citation_ok_rate,
            "null_rate_on_ref_valued": self.null_rate_on_ref_valued,
            "per_field": {
                k: {"tp": c.tp, "fp": c.fp, "fn": c.fn, "precision": c.precision,
                    "recall": c.recall, "f1": c.f1}
                for k, c in sorted(self.per_field.items())
            },
        }

    def render(self) -> str:
        lines = [f"{'pole':45} {'TP':>5} {'FP':>5} {'FN':>5} {'P':>6} {'R':>6} {'F1':>6}"]
        for key, c in sorted(self.per_field.items()):
            lines.append(
                f"{key:45} {c.tp:5d} {c.fp:5d} {c.fn:5d} {c.precision:6.3f} {c.recall:6.3f} {c.f1:6.3f}"
            )
        lines += [
            "",
            f"dokumenty (z referencją):        {self.docs}",
            f"F1 (micro):                      {self.micro_f1:.4f}",
            f"precision / recall:              {self.precision:.4f} / {self.recall:.4f}",
            f"exact match na dokument:         {self.doc_exact_match:.4f}",
            f"poprawna klasyfikacja:           {self.classification_accuracy:.4f}",
            f"poprawne cytaty:                 {self.citation_ok_rate:.4f}",
            f"null przy polach z referencją:   {self.null_rate_on_ref_valued:.4f}",
        ]
        return "\n".join(lines)


def _evaluate_example(
    example: Path, classes: dict[str, ClassConfig], llm: LLM, settings: Settings
) -> Report:
    report = Report()
    results = [process_pdf(p, classes, llm, settings) for p in sorted(example.glob("*.pdf"))]
    refs = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(example.glob("*.json"))
        if p.stem in classes
    }
    scored: set[int] = set()
    for class_name, ref in refs.items():
        matching = [r for r in results if r.class_name == class_name and r.data is not None]
        report.classified_total += 1
        report.classified_ok += bool(matching)
        pred = matching[0].data if matching else None
        if matching:
            scored.add(id(matching[0]))
        report.add_document(score_document(pred, ref, classes[class_name]))
    for r in results:
        if r.data is not None and id(r) not in scored:
            report.add_counts(score_document(r.data, {}, classes[r.class_name]))
        if r.extraction is not None:
            report.cited_total += len(r.extraction.citation_ok)
            report.cited_ok += sum(r.extraction.citation_ok.values())
        if r.error:
            log.warning("%s: %s", r.path, r.error)
    return report


def evaluate(
    data_dir: Path,
    classes: dict[str, ClassConfig],
    llm: LLM,
    settings: Settings,
    limit: int | None = None,
    workers: int = 4,
) -> Report:
    examples = sorted(p for p in Path(data_dir).glob("przyklad_*") if p.is_dir())
    if limit is not None:
        examples = examples[:limit]
    total = Report()
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        for i, part in enumerate(
            pool.map(lambda e: _evaluate_example(e, classes, llm, settings), examples), 1
        ):
            total.merge(part)
            log.info("eval %d/%d", i, len(examples))
    return total
