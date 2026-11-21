from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.classconfig import ClassConfig, FieldSpec
from src.llm import LLM
from src.pipeline import DocResult, _trace, process_pdf
from src.settings import Settings
from src.validators import date as normalize_date

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
    if spec.type in ("integer", "number") and re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
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


def _labels(item: dict, spec: FieldSpec) -> set[str]:
    labels = set()
    for key in spec.key:
        value = _lookup(item, key)
        if value not in (None, ""):
            labels.add(f"{key}={_norm(value, FieldSpec(name=key, type='text'))}")
    return labels


def _pair_items(
    pred_items: list, ref_items: list, spec: FieldSpec
) -> list[tuple[dict | None, dict | None, str]]:
    """Paruje elementy tablicy: najpierw po wspólnej wartości klucza, resztę po kolejności."""
    ref_labels = [_labels(r, spec) for r in ref_items]
    pred_labels = [_labels(p, spec) for p in pred_items]
    matched: dict[int, int] = {}
    used: set[int] = set()
    for i, rl in enumerate(ref_labels):
        for j, pl in enumerate(pred_labels):
            if j not in used and rl & pl:
                matched[i] = j
                used.add(j)
                break
    left_ref = [i for i in range(len(ref_items)) if i not in matched]
    left_pred = [j for j in range(len(pred_items)) if j not in used]
    for i, j in zip(left_ref, left_pred, strict=False):
        matched[i] = j
        used.add(j)
    pairs: list[tuple[dict | None, dict | None, str]] = []
    for i, ref_item in enumerate(ref_items):
        pred_item = pred_items[matched[i]] if i in matched else None
        pairs.append((pred_item, ref_item, _item_label(ref_item, spec, i)))
    for j, pred_item in enumerate(pred_items):
        if j not in used:
            pairs.append((pred_item, None, "+" + _item_label(pred_item, spec, j)))
    return pairs


def _walk_pair(
    pred: dict,
    ref: dict,
    fields: list[FieldSpec],
    prefix: str,
    out_pred: dict[str, Any],
    out_ref: dict[str, Any],
) -> None:
    for spec in fields:
        pv = pred.get(spec.name) if isinstance(pred, dict) else None
        rv = ref.get(spec.name) if isinstance(ref, dict) else None
        path = f"{prefix}{spec.name}"
        if spec.type == "object":
            _walk_pair(pv or {}, rv or {}, spec.fields, f"{path}.", out_pred, out_ref)
        elif spec.type == "array":
            for p_item, r_item, label in _pair_items(pv or [], rv or [], spec):
                _walk_pair(
                    p_item or {}, r_item or {}, spec.fields, f"{path}[{label}].", out_pred, out_ref
                )
        else:
            out_pred[path] = _norm(pv, spec)
            out_ref[path] = _norm(rv, spec)


def _schema_path(path: str) -> str:
    return re.sub(r"\[[^\]]*\]", "[]", path)


def score_document(pred: dict | None, ref: dict, cfg: ClassConfig) -> dict[str, Counts]:
    pred_flat: dict[str, Any] = {}
    ref_flat: dict[str, Any] = {}
    _walk_pair(pred or {}, ref or {}, cfg.fields, "", pred_flat, ref_flat)
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


def diff_document(pred: dict | None, ref: dict | None, cfg: ClassConfig) -> list[dict]:
    """Różnice pole po polu (to, co score_document zlicza jako FP/FN).

    Wartości są w postaci znormalizowanej, tak jak porównuje eval.
    """
    pred_flat: dict[str, Any] = {}
    ref_flat: dict[str, Any] = {}
    _walk_pair(pred or {}, ref or {}, cfg.fields, "", pred_flat, ref_flat)
    diffs = []
    for path in sorted(set(pred_flat) | set(ref_flat)):
        p, r = pred_flat.get(path), ref_flat.get(path)
        if p == r:
            continue
        status = "wrong" if p is not None and r is not None else "missing" if p is None else "extra"
        diffs.append({"field": path, "predicted": p, "expected": r, "status": status})
    return diffs


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class Report:
    per_field: dict[str, Counts] = field(default_factory=dict)
    docs: int = 0
    doc_exact: int = 0
    classified_ok: int = 0
    classified_total: int = 0
    cited_ok: int = 0
    cited_total: int = 0
    # Awarie (dokument z `error`, np. model niedostępny) oddzielone od jakości ekstrakcji:
    # per_field_clean pomija referencje, których brak wynika z awarii w danym przykładzie.
    errors: int = 0
    docs_lost_to_errors: int = 0
    per_field_clean: dict[str, Counts] = field(default_factory=dict)

    def add_counts(self, counts: dict[str, Counts], clean: bool = True) -> None:
        for key, c in counts.items():
            self.per_field[key] = self.per_field.get(key, Counts()) + c
            if clean:
                self.per_field_clean[key] = self.per_field_clean.get(key, Counts()) + c

    def add_document(self, counts: dict[str, Counts], clean: bool = True) -> None:
        self.add_counts(counts, clean)
        self.docs += 1
        if not clean:
            self.docs_lost_to_errors += 1
        if all(c.fp == 0 and c.fn == 0 for c in counts.values()):
            self.doc_exact += 1

    def merge(self, other: Report) -> None:
        self.add_counts(other.per_field, clean=False)
        for key, c in other.per_field_clean.items():
            self.per_field_clean[key] = self.per_field_clean.get(key, Counts()) + c
        for name in (
            "docs",
            "doc_exact",
            "classified_ok",
            "classified_total",
            "cited_ok",
            "cited_total",
            "errors",
            "docs_lost_to_errors",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def totals(self) -> Counts:
        out = Counts()
        for c in self.per_field.values():
            out = out + c
        return out

    @property
    def totals_clean(self) -> Counts:
        out = Counts()
        for c in self.per_field_clean.values():
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
            "errors": self.errors,
            "docs_lost_to_errors": self.docs_lost_to_errors,
            "micro_f1_without_errors": self.totals_clean.f1,
            "precision_without_errors": self.totals_clean.precision,
            "recall_without_errors": self.totals_clean.recall,
            "doc_exact_match": self.doc_exact_match,
            "classification_accuracy": self.classification_accuracy,
            "citation_ok_rate": self.citation_ok_rate,
            "null_rate_on_ref_valued": self.null_rate_on_ref_valued,
            "per_field": {
                k: {
                    "tp": c.tp,
                    "fp": c.fp,
                    "fn": c.fn,
                    "precision": c.precision,
                    "recall": c.recall,
                    "f1": c.f1,
                }
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
            f"PDF z błędem (awaria):           {self.errors}"
            f" (referencji utraconych: {self.docs_lost_to_errors})",
            f"F1 bez dokumentów z błędem:      {self.totals_clean.f1:.4f}"
            f" (P {self.totals_clean.precision:.4f} / R {self.totals_clean.recall:.4f})",
            f"exact match na dokument:         {self.doc_exact_match:.4f}",
            f"poprawna klasyfikacja:           {self.classification_accuracy:.4f}",
            f"poprawne cytaty:                 {self.citation_ok_rate:.4f}",
            f"null przy polach z referencją:   {self.null_rate_on_ref_valued:.4f}",
        ]
        return "\n".join(lines)


def _ref_class(ref: dict, classes: dict[str, ClassConfig]) -> str | None:
    """Klasa referencji o nazwie niezgodnej z klasą (skany: `0001.json`): po kluczach najwyższego poziomu."""
    keys = set(ref)
    best, best_n = None, 0
    for name, cfg in classes.items():
        n = len(keys & {f.name for f in cfg.fields})
        if n > best_n:
            best, best_n = name, n
    return best


def _label(example: Path) -> str:
    """Nazwa katalogu w dumpie; skany mają powtarzalne numery (odwolania/0001), więc dostają prefiks."""
    return f"{example.parent.name}_{example.name}" if example.name.isdigit() else example.name


def _find_examples(data_dir: Path) -> list[Path]:
    """`przyklad_*` albo, gdy ich brak (skany, negatywne), każdy katalog z PDF-ami."""
    data_dir = Path(data_dir)
    examples = sorted(p for p in data_dir.glob("przyklad_*") if p.is_dir())
    if examples:
        return examples
    return sorted({p.parent for p in data_dir.rglob("*.pdf")})


def _evaluate_example(
    example: Path,
    classes: dict[str, ClassConfig],
    llm: LLM,
    settings: Settings,
    dump_dir: Path | None = None,
) -> Report:
    report = Report()
    results = [process_pdf(p, classes, llm, settings) for p in sorted(example.glob("*.pdf"))]
    # Klasa referencji wynika z jej treści (klucze), nie z nazwy pliku.
    refs: list[tuple[str, str, dict]] = []
    for p in sorted(example.glob("*.json")):
        ref = json.loads(p.read_text(encoding="utf-8"))
        name = _ref_class(ref, classes)
        if name:
            refs.append((p.stem, name, ref))
    scored: dict[int, dict] = {}
    missed: dict[str, dict] = {}
    report.errors = sum(1 for r in results if r.error)
    for stem, class_name, ref in refs:
        # Para po nazwie pliku (abc.pdf <-> abc.json); gdy brak, pierwszy wolny dokument tej klasy.
        free = [r for r in results if r.data is not None and id(r) not in scored]
        by_stem = [r for r in free if r.path is not None and r.path.stem == stem]
        matching = [r for r in (by_stem or free) if r.class_name == class_name][:1]
        report.classified_total += 1
        report.classified_ok += bool(matching)
        pred = matching[0].data if matching else None
        if matching:
            scored[id(matching[0])] = ref
        else:
            missed[stem] = {
                "reason": "brak dokumentu tej klasy",
                "expected": ref,
                "diffs": diff_document(None, ref, classes[class_name]),
            }
        # Brak dokumentu przy awarii w tym przykładzie: nie wliczamy do F1 „bez błędów”.
        lost = not matching and report.errors > 0
        report.add_document(score_document(pred, ref, classes[class_name]), clean=not lost)
    for r in results:
        if r.data is not None and id(r) not in scored:
            report.add_counts(score_document(r.data, {}, classes[r.class_name]))
        if r.extraction is not None:
            report.cited_total += len(r.extraction.citation_ok)
            report.cited_ok += sum(r.extraction.citation_ok.values())
        if r.error:
            log.warning("%s: %s", r.path, r.error)
        if dump_dir is not None and r.path is not None:
            _dump_result(dump_dir / _label(example), r, scored.get(id(r)), classes)
    if dump_dir is not None and missed:
        _dump_json(dump_dir / _label(example) / "_missed.json", missed)
    return report


def _dump_result(
    out_dir: Path, r: DocResult, ref: dict | None, classes: dict[str, ClassConfig]
) -> None:
    assert r.path is not None
    diffs = diff_document(r.data, ref or {}, classes[r.class_name]) if r.data is not None else []
    _dump_json(
        out_dir / f"{r.path.stem}.json",
        {
            "source": r.path.name,
            "class": r.class_name,
            "error": r.error,
            "ocr_used": r.ocr_used,
            "prediction": r.data,
            "reference": ref,
            "diffs": diffs,
            "trace": _trace(r, Path(r.path.name)) if r.extraction is not None else None,
        },
    )


def example_name(value: str) -> str:
    """„1”, „01” albo „przyklad_01” → „przyklad_01”."""
    value = value.strip()
    return f"przyklad_{int(value):02d}" if value.isdigit() else value


def evaluate(
    data_dir: Path,
    classes: dict[str, ClassConfig],
    llm: LLM,
    settings: Settings,
    limit: int | None = None,
    workers: int = 4,
    dump_dir: Path | None = None,
    only: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> Report:
    examples = _find_examples(data_dir)
    if only:
        wanted = {example_name(x) for x in only}
        examples = [e for e in examples if e.name in wanted]
        missing = wanted - {e.name for e in examples}
        if missing:
            log.warning("Nie znaleziono przykładów: %s", ", ".join(sorted(missing)))
    if limit is not None:
        examples = examples[:limit]
    total = Report()
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        for i, part in enumerate(
            pool.map(lambda e: _evaluate_example(e, classes, llm, settings, dump_dir), examples), 1
        ):
            total.merge(part)
            log.info("eval %d/%d", i, len(examples))
            if on_progress:
                on_progress(i, len(examples))
    return total
