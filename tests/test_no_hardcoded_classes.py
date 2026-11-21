import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "odwolania2json"
FORBIDDEN = re.compile(r"odwolanie|pelnomocnictwo|przelew", re.IGNORECASE)


def test_no_class_names_in_package():
    hits = [
        f"{p.name}:{i}: {line.strip()}"
        for p in PACKAGE.glob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert hits == []
