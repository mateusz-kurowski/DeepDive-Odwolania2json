"""Ewaluacja w API: wyniki lokalne (results/, tylko odczyt) i przebiegi z UI w object storage."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from src.api.storage import NotFound, Storage
from src.classconfig import load_classes
from src.evaluate import Counts, _find_examples, evaluate, score_document
from src.llm import LLM
from src.models import load_model_sizes
from src.settings import Settings

log = logging.getLogger(__name__)

PREFIX = "evaluations/"
_SAFE = re.compile(r"[\w][\w.\- ]*")


class EvaluationError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _summary_fields(report: dict) -> dict:
    return {
        "micro_f1": report.get("micro_f1"),
        "precision": report.get("precision"),
        "recall": report.get("recall"),
        "docs": report.get("docs"),
        "errors": report.get("errors"),
        "citation_ok_rate": report.get("citation_ok_rate"),
    }


def _examples_from_keys(prefix: str, keys: list[str]) -> list[str]:
    """Te same reguły co `_find_examples`, ale na kluczach S3: zwraca prefiksy katalogów przykładów."""
    rels = [k[len(prefix) :] for k in keys if k.startswith(prefix)]
    first = {r.split("/")[0] for r in rels if "/" in r}
    examples = sorted(d for d in first if d.startswith("przyklad_"))
    if examples:
        return [prefix + d + "/" for d in examples]
    return sorted({prefix + r.rsplit("/", 1)[0] + "/" for r in rels if r.lower().endswith(".pdf")})


@lru_cache(maxsize=1)
def _model_sizes() -> dict[str, float]:
    return load_model_sizes()


def _norm_prefix(prefix: str) -> str:
    return prefix.strip("/") + "/"


def load_datasets(config: Path, storage: Storage | None = None) -> list[dict]:
    """Zbiór ma `prefix` (klucze w S3) i/lub `path` (lokalny katalog). S3 ma pierwszeństwo, lokalny to fallback."""
    if not config.is_file():
        return []
    raw = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    out = []
    for item in raw.get("datasets", []):
        path = Path(item["path"]) if item.get("path") else None
        prefix = _norm_prefix(item["prefix"]) if item.get("prefix") else None
        remote = 0
        if prefix and storage is not None:
            try:
                remote = len(_examples_from_keys(prefix, storage.list(prefix)))
            except Exception:
                log.exception("Nie udało się wylistować zbioru %s w storage", item["id"])
        local = len(_find_examples(path)) if path and path.is_dir() else 0
        out.append(
            {
                "id": item["id"],
                "name": item.get("name", item["id"]),
                "description": item.get("description", ""),
                "path": str(path) if path else None,
                "prefix": prefix,
                "source": "storage" if remote else ("local" if local else None),
                "examples": remote or local,
            }
        )
    return out


class EvaluationService:
    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        llm_factory: Callable[[Settings], LLM],
        datasets_config: Path,
        results_dir: Path,
    ):
        self.storage = storage
        self.settings = settings
        self.llm_factory = llm_factory
        self.datasets_config = Path(datasets_config)
        self.results_dir = Path(results_dir)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")
        self._io = ThreadPoolExecutor(max_workers=8, thread_name_prefix="eval-io")
        # path -> ((mtime_ns, size), run, report): raporty lokalne parsujemy tylko po zmianie pliku
        self._local_cache: dict[Path, tuple[tuple[int, int], dict | None, dict | None]] = {}

    # --- zbiory ------------------------------------------------------------------------------
    def datasets(self) -> list[dict]:
        return load_datasets(self.datasets_config, self.storage)

    # --- wyniki lokalne ----------------------------------------------------------------------
    def _local_files(self) -> list[Path]:
        found: list[Path] = []
        if not self.results_dir.is_dir():
            return found
        for root, dirs, files in os.walk(self.results_dir):
            dirs[:] = [d for d in dirs if not d.startswith("dump")]
            found += [Path(root) / f for f in files if f.endswith(".json") and f != "summary.json"]
        return sorted(found)

    def _local_id(self, path: Path) -> str:
        rel = path.relative_to(self.results_dir).with_suffix("")
        return "local-" + "__".join(rel.parts)

    def _local_dump(self, path: Path) -> Path:
        name = "dump" if path.stem == "report" else f"dump-{path.stem}"
        return path.parent / name

    def _local_runs(self) -> list[tuple[dict, Path]]:
        runs = []
        seen = set()
        for path in self._local_files():
            seen.add(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            sig = (stat.st_mtime_ns, stat.st_size)
            cached = self._local_cache.get(path)
            if cached is None or cached[0] != sig:
                cached = (sig, *self._parse_local(path, stat.st_mtime))
                self._local_cache[path] = cached
            if cached[1] is not None:
                runs.append((cached[1], path))
        for gone in set(self._local_cache) - seen:
            del self._local_cache[gone]
        return runs

    def _parse_local(self, path: Path, mtime: float) -> tuple[dict | None, dict | None]:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        if not (isinstance(report, dict) and "per_field" in report and "micro_f1" in report):
            return None, None
        rel = path.relative_to(self.results_dir).with_suffix("")
        run = {
            "id": self._local_id(path),
            "source": "local",
            "name": "/".join(rel.parts[:-1] + (() if rel.name == "report" else (rel.name,)))
            or rel.name,
            "dataset": None,
            "model": report.get("model"),
            "mode": report.get("mode"),
            "status": "done",
            "started_at": None,
            "finished_at": _iso(mtime),
            "error": None,
            "progress": None,
            **_summary_fields(report),
        }
        return run, report

    # --- wyniki w storage --------------------------------------------------------------------
    def _storage_runs(self) -> list[dict]:
        keys = [k for k in self.storage.list(PREFIX) if k.endswith("/run.json")]

        def load(key: str) -> dict | None:
            try:
                return json.loads(self.storage.get(key))
            except (NotFound, ValueError):
                return None

        return [r for r in self._io.map(load, keys) if r is not None]

    def _save_run(self, run: dict) -> None:
        self.storage.put(
            f"{PREFIX}{run['id']}/run.json",
            json.dumps(run, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )

    @staticmethod
    def _with_size(run: dict) -> dict:
        """Dopisuje rozmiar modelu w mld parametrów (config/models.yaml); None, gdy nieznany."""
        return {**run, "model_params_b": _model_sizes().get(run.get("model") or "")}

    def list_runs(self) -> list[dict]:
        runs = [self._with_size(r) for r, _ in self._local_runs()]
        runs += [self._with_size(r) for r in self._storage_runs()]
        runs.sort(key=lambda r: r.get("finished_at") or r.get("started_at") or "", reverse=True)
        return runs

    def get_run(self, run_id: str) -> dict:
        for run, path in self._local_runs():
            if run["id"] == run_id:
                return {**self._with_size(run), "report": self._local_cache[path][2]}
        if re.fullmatch(r"s-[0-9a-f]{32}", run_id):
            try:
                run = json.loads(self.storage.get(f"{PREFIX}{run_id}/run.json"))
            except NotFound:
                raise EvaluationError("Nie znaleziono przebiegu.", 404) from None
            try:
                report = json.loads(self.storage.get(f"{PREFIX}{run_id}/report.json"))
            except NotFound:
                report = None
            return {**self._with_size(run), "report": report}
        raise EvaluationError("Nie znaleziono przebiegu.", 404)

    # --- usuwanie i przypinanie --------------------------------------------------------------
    def _storage_run(self, run_id: str) -> dict:
        """Przebieg z UI (storage). Lokalne wyniki z results/ są tylko do odczytu."""
        if any(run["id"] == run_id for run, _ in self._local_runs()):
            raise EvaluationError("Wyniki lokalne są tylko do odczytu.", 409)
        if not re.fullmatch(r"s-[0-9a-f]{32}", run_id):
            raise EvaluationError("Nie znaleziono przebiegu.", 404)
        try:
            return json.loads(self.storage.get(f"{PREFIX}{run_id}/run.json"))
        except NotFound:
            raise EvaluationError("Nie znaleziono przebiegu.", 404) from None

    def set_pinned(self, run_id: str, pinned: bool) -> dict:
        run = self._storage_run(run_id)
        if run.get("status") == "running":
            raise EvaluationError("Przebieg trwa; przypnij go po zakończeniu.", 409)
        run["pinned"] = pinned
        self._save_run(run)
        return self._with_size(run)

    def delete_run(self, run_id: str) -> None:
        run = self._storage_run(run_id)
        if run.get("status") == "running":
            raise EvaluationError("Przebieg trwa; nie można go usunąć.", 409)
        if run.get("pinned"):
            raise EvaluationError("Przebieg jest przypięty; najpierw go odepnij.", 409)
        for key in self.storage.list(f"{PREFIX}{run_id}/"):
            self.storage.delete(key)

    # --- uruchamianie z UI -------------------------------------------------------------------
    def start(
        self,
        dataset_id: str,
        model: str | None = None,
        mode: str | None = None,
        limit: int | None = None,
    ) -> dict:
        dataset = next((d for d in self.datasets() if d["id"] == dataset_id), None)
        if dataset is None:
            raise EvaluationError(f"Nieznany zbiór danych: {dataset_id}", 404)
        if dataset["examples"] == 0:
            raise EvaluationError(f"Zbiór '{dataset_id}' jest pusty lub niedostępny (lokalnie i w storage).", 409)
        if mode not in (None, "hybrid", "llm_only"):
            raise EvaluationError("Tryb: hybrid lub llm_only.", 422)
        if limit is not None and limit < 1:
            raise EvaluationError("Limit musi być dodatni.", 422)
        settings = self.settings.model_copy(
            update={
                "llm_model": model or self.settings.llm_model,
                "extraction_mode": mode or self.settings.extraction_mode,
            }
        )
        if not settings.llm_model:
            raise EvaluationError("Brak modelu: podaj model lub ustaw LLM_MODEL.", 422)
        run = {
            "id": f"s-{uuid.uuid4().hex}",
            "source": "storage",
            "name": f"{dataset['name']} · {settings.llm_model}",
            "dataset": dataset_id,
            "model": settings.llm_model,
            "mode": settings.extraction_mode,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "error": None,
            "progress": {
                "done": 0,
                "total": min(dataset["examples"], limit or dataset["examples"]),
            },
            **_summary_fields({}),
        }
        self._save_run(run)
        self._pool.submit(self._execute, run, dataset, settings, limit)
        return run

    def resume(self) -> None:
        """Przebieg przerwany restartem nie wznawia się sam: oznaczamy go jako błąd."""
        for run in self._storage_runs():
            if run.get("status") == "running":
                run.update(status="error", error="Przerwano restartem API.", finished_at=_now())
                self._save_run(run)

    def _download_dataset(self, prefix: str, dest: Path, limit: int | None) -> Path:
        """Pobiera ze storage tylko przykłady potrzebne do przebiegu (pierwsze `limit`)."""
        keys = self.storage.list(prefix)
        wanted = _examples_from_keys(prefix, keys)[: limit or None]
        for key in keys:
            if any(key.startswith(w) for w in wanted):
                target = dest / key[len(prefix) :]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.storage.get(key))
        return dest

    def _execute(self, run: dict, dataset: dict, settings: Settings, limit: int | None) -> None:
        try:
            classes = load_classes(settings.classes_dir)
            llm = self.llm_factory(settings)

            def progress(done: int, total: int) -> None:
                run["progress"] = {"done": done, "total": total}
                self._save_run(run)

            with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as src:
                dump = Path(tmp)
                if dataset["source"] == "storage":
                    data = self._download_dataset(dataset["prefix"], Path(src), limit)
                else:
                    data = Path(dataset["path"])
                report = evaluate(
                    data,
                    classes,
                    llm,
                    settings,
                    limit=limit,
                    workers=4,
                    dump_dir=dump,
                    on_progress=progress,
                )
                payload = {
                    **report.to_dict(),
                    "model": settings.llm_model,
                    "mode": settings.extraction_mode,
                }
                usage = getattr(llm, "usage", None)
                if usage:
                    payload["usage"] = usage.to_dict()
                for file in dump.rglob("*.json"):
                    rel = file.relative_to(dump).as_posix()
                    self.storage.put(
                        f"{PREFIX}{run['id']}/dump/{rel}", file.read_bytes(), "application/json"
                    )
            self.storage.put(
                f"{PREFIX}{run['id']}/report.json",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
            run.update(status="done", finished_at=_now(), **_summary_fields(payload))
        except Exception as exc:
            log.exception("Ewaluacja %s nieudana", run["id"])
            run.update(status="error", error=f"{type(exc).__name__}: {exc}", finished_at=_now())
        self._save_run(run)

    # --- dokumenty przebiegu -----------------------------------------------------------------
    def _dump_names(self, run_id: str) -> list[tuple[str, str]]:
        names: list[tuple[str, str]] = []
        local = next((p for r, p in self._local_runs() if r["id"] == run_id), None)
        if local is not None:
            base = self._local_dump(local)
            if base.is_dir():
                for f in sorted(base.glob("*/*.json")):
                    names.append((f.parent.name, f.stem))
        else:
            prefix = f"{PREFIX}{run_id}/dump/"
            for key in self.storage.list(prefix):
                parts = key[len(prefix) :].split("/")
                if len(parts) == 2 and parts[1].endswith(".json"):
                    names.append((parts[0], parts[1][:-5]))
        return [(label, stem) for label, stem in names if stem != "_missed"]

    def _read_dump(self, run_id: str, local: Path | None, label: str, stem: str) -> dict:
        if not (_SAFE.fullmatch(label) and _SAFE.fullmatch(stem)) or ".." in label + stem:
            raise EvaluationError("Niepoprawna nazwa dokumentu.", 404)
        try:
            if local is not None:
                return json.loads(
                    (self._local_dump(local) / label / f"{stem}.json").read_text("utf-8")
                )
            return json.loads(self.storage.get(f"{PREFIX}{run_id}/dump/{label}/{stem}.json"))
        except (FileNotFoundError, NotFound):
            raise EvaluationError("Nie znaleziono dokumentu w przebiegu.", 404) from None

    def read_document(self, run_id: str, label: str, stem: str) -> dict:
        if not (_SAFE.fullmatch(label) and _SAFE.fullmatch(stem)) or ".." in label + stem:
            raise EvaluationError("Niepoprawna nazwa dokumentu.", 404)
        self.get_run(run_id)
        local = next((p for r, p in self._local_runs() if r["id"] == run_id), None)
        return self._read_dump(run_id, local, label, stem)

    def documents(self, run_id: str) -> list[dict]:
        self.get_run(run_id)
        local = next((p for r, p in self._local_runs() if r["id"] == run_id), None)
        classes = load_classes(self.settings.classes_dir)

        def row(item: tuple[str, str]) -> dict:
            label, stem = item
            doc = self._read_dump(run_id, local, label, stem)
            cls = doc.get("class")
            tp = fp = fn = None
            f1 = None
            if (
                doc.get("reference") is not None
                and doc.get("prediction") is not None
                and cls in classes
            ):
                total = Counts()
                for c in score_document(doc["prediction"], doc["reference"], classes[cls]).values():
                    total = total + c
                tp, fp, fn, f1 = total.tp, total.fp, total.fn, total.f1
            return {
                "label": label,
                "stem": stem,
                "class_name": cls,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "f1": f1,
                "error": doc.get("error"),
            }

        return list(self._io.map(row, self._dump_names(run_id)))
