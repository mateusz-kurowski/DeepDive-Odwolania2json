"""Wgrywa lokalne zbiory ewaluacyjne (config/eval-datasets.yaml) do object storage pod ich `prefix`.

    uv run --extra api python -m scripts.upload_datasets [config/eval-datasets.yaml]

Konfiguracja S3_* jest czytana z pliku .env w katalogu projektu (ma pierwszeństwo przed zmiennymi
powłoki, żeby nie trafić przypadkiem na inny bucket/endpoint), patrz .env.example.
Wgrywa pliki .pdf i .json (nadpisuje istniejące klucze).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

from src.api.storage import make_storage

EXT = {".pdf": "application/pdf", ".json": "application/json"}


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("\"'")
    return env


def main(config: Path) -> int:
    storage = make_storage({**os.environ, **load_dotenv(Path(".env"))})
    if storage.backend != "s3":
        print("Ustaw S3_BUCKET (i dane dostępowe) – bez tego wgrywanie nie ma sensu.", file=sys.stderr)
        return 1
    done: set[Path] = set()
    for item in yaml.safe_load(config.read_text(encoding="utf-8")).get("datasets", []):
        if not (item.get("path") and item.get("prefix")):
            continue
        root, prefix = Path(item["path"]), item["prefix"].strip("/")
        for f in sorted(root.rglob("*")):
            if f.suffix.lower() not in EXT or f in done:
                continue
            done.add(f)
            key = f"{prefix}/{f.relative_to(root).as_posix()}"
            storage.put(key, f.read_bytes(), EXT[f.suffix.lower()])
        print(f"{item['id']}: {len(storage.list(prefix + '/'))} kluczy -> s3://{storage.bucket}/{prefix}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "config/eval-datasets.yaml")))
