import hashlib
import shutil
from pathlib import Path

from odwolania2json.cli import main
from odwolania2json.pipeline import process_text
from odwolania2json.classconfig import load_classes
from odwolania2json.textextract import DocText

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "odwolania2json"


def package_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(PACKAGE.glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def classes_with_faktura(tmp_path) -> Path:
    target = tmp_path / "classes"
    shutil.copytree(ROOT / "classes", target)
    shutil.copy(ROOT / "classes_examples" / "faktura.yaml", target / "faktura.yaml")
    return target


INVOICE = "Faktura VAT nr FV/12/2026 z dnia 2026-02-03. Sprzedawca: Alfa Sp. z o.o. NIP 527-000-00-00. Nabywca: Beta S.A. NIP 9994150873. Razem brutto: 1 230,00 zł."


def cell(value, quote):
    return {"value": value, "quote": quote}


ANSWER = {
    "numer_faktury": cell("FV/12/2026", "Faktura VAT nr FV/12/2026"),
    "data_wystawienia": cell("2026-02-03", "z dnia 2026-02-03"),
    "sprzedawca": {"nazwa": cell("Alfa Sp. z o.o.", "Alfa Sp. z o.o."), "nip": cell("527-000-00-00", "NIP 527-000-00-00")},
    "nabywca": {"nazwa": cell("Beta S.A.", "Beta S.A."), "nip": cell("9994150873", "NIP 9994150873")},
    "kwota_brutto": cell("1 230,00 zł", "brutto: 1 230,00 zł"),
}


def test_new_class_added_by_yaml_only(tmp_path, fake_llm):
    before = package_hash()
    classes = load_classes(classes_with_faktura(tmp_path))
    llm = fake_llm([{"class": "faktura"}, ANSWER])
    result = process_text(DocText(INVOICE, 1, False), classes, llm, "hybrid", 85)
    assert result.class_name == "faktura"
    assert result.data == {
        "numer_faktury": "FV/12/2026",
        "data_wystawienia": "2026-02-03",
        "sprzedawca": {"nazwa": "Alfa Sp. z o.o.", "nip": "5270000000"},
        "nabywca": {"nazwa": "Beta S.A.", "nip": "9994150873"},
        "kwota_brutto": 1230.0,
    }
    assert "faktura" in llm.calls[0]["schema"]["properties"]["class"]["enum"]
    assert package_hash() == before


def test_new_class_visible_in_classes_cli(tmp_path, capsys):
    classes_dir = classes_with_faktura(tmp_path)
    assert main(["classes", "--classes", str(classes_dir)], env={}) == 0
    out = capsys.readouterr().out
    assert "faktura" in out and "przelew" in out and "odwolanie" in out
