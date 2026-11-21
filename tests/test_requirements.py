"""requirements.txt (wymóg dostawy) musi być zgodny z uv.lock."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_requirements_txt_matches_uv_lock():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = {p["name"]: p["version"] for p in lock["package"]}
    pins = _pins(ROOT / "requirements.txt")
    assert pins, "requirements.txt jest pusty: uruchom `make requirements`"
    for name, version in pins.items():
        assert locked.get(name) == version, f"{name}: lock={locked.get(name)}, req={version}"


def test_requirements_txt_has_direct_dependencies():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pins = _pins(ROOT / "requirements.txt")
    for dep in pyproject["project"]["dependencies"]:
        name = re.split(r"[<>=\[ ;]", dep, maxsplit=1)[0].lower().replace("_", "-")
        assert name in pins, f"brak {name} w requirements.txt: uruchom `make requirements`"
