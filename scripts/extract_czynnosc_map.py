"""Odtwarza słownik czynnosc_powod_id → czynnosc_opis z referencji organizatora.

Użycie: python scripts/extract_czynnosc_map.py [katalog_danych]
Kończy się błędem, gdy jeden identyfikator ma kilka różnych opisów.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def collect(data_dir: Path) -> dict[int, set[str]]:
    found: dict[int, set[str]] = defaultdict(set)
    for path in sorted(data_dir.glob("przyklad_*/odwolanie.json")):
        info = json.loads(path.read_text(encoding="utf-8")).get("OdwolanieKIO", {})
        if info.get("czynnosc_powod_id") is not None and info.get("czynnosc_opis"):
            found[info["czynnosc_powod_id"]].add(info["czynnosc_opis"])
    return found


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/dane")
    found = collect(data_dir)
    conflicts = {k: v for k, v in found.items() if len(v) > 1}
    for key in sorted(found):
        for desc in sorted(found[key]):
            print(f"{key}: {desc}")
    if conflicts:
        print(f"BŁĄD: niejednoznaczne opisy dla id {sorted(conflicts)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
