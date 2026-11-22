from src.api.evaluation import EvaluationService, _examples_from_keys, load_datasets
from src.api.storage import LocalStorage

CONFIG = """datasets:
  - id: dane
    name: Dane
    path: nie-istnieje/dane
    prefix: datasets/dane
"""


def _fill(storage):
    for ex in ("przyklad_01", "przyklad_02", "przyklad_03"):
        storage.put(f"datasets/dane/{ex}/odwolanie.pdf", b"%PDF")
        storage.put(f"datasets/dane/{ex}/odwolanie.json", b"{}")
    storage.put("datasets/dane/skany/a/x.pdf", b"%PDF")


def test_examples_from_keys_prefers_przyklad():
    keys = ["p/przyklad_02/a.pdf", "p/przyklad_01/a.pdf", "p/skany/x/b.pdf"]
    assert _examples_from_keys("p/", keys) == ["p/przyklad_01/", "p/przyklad_02/"]


def test_examples_from_keys_falls_back_to_pdf_dirs():
    keys = ["p/a/x.pdf", "p/a/y.pdf", "p/b/z.pdf", "p/b/z.json"]
    assert _examples_from_keys("p/", keys) == ["p/a/", "p/b/"]


def test_load_datasets_reads_from_storage_when_no_local(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    storage = LocalStorage(tmp_path / "s")
    assert load_datasets(cfg, storage)[0]["examples"] == 0
    _fill(storage)
    ds = load_datasets(cfg, storage)[0]
    assert (ds["examples"], ds["source"]) == (3, "storage")


def test_download_respects_limit(tmp_path):
    storage = LocalStorage(tmp_path / "s")
    _fill(storage)
    svc = EvaluationService(storage, None, None, tmp_path / "c.yaml", tmp_path / "r")
    out = tmp_path / "out"
    svc._download_dataset("datasets/dane/", out, 2)
    assert sorted(p.name for p in out.iterdir()) == ["przyklad_01", "przyklad_02"]


def test_storage_wins_over_local(tmp_path):
    local = tmp_path / "dane" / "przyklad_01"
    local.mkdir(parents=True)
    (local / "a.pdf").write_bytes(b"%PDF")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(CONFIG.replace("nie-istnieje/dane", str(tmp_path / "dane")), encoding="utf-8")
    storage = LocalStorage(tmp_path / "s")
    assert load_datasets(cfg, storage)[0]["source"] == "local"
    _fill(storage)
    ds = load_datasets(cfg, storage)[0]
    assert (ds["source"], ds["examples"]) == ("storage", 3)
