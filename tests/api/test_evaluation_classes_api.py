import json
import time

import yaml

CLASS_YAML = """
name: nowa
description: Nowy typ
fields:
  - {name: numer, type: text}
"""


def _dataset(tmp_path):
    ex = tmp_path / "data" / "przyklad_01"
    ex.mkdir(parents=True)
    (ex / "a.pdf").write_bytes(b"%PDF")
    (ex / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    (tmp_path / "datasets.yaml").write_text(
        yaml.safe_dump(
            {"datasets": [{"id": "d", "name": "Zbiór D", "path": str(tmp_path / "data")}]}
        ),
        encoding="utf-8",
    )


def _wait_run(client, run_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/evaluation/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("ewaluacja nie skończyła się")


def test_run_from_ui_is_saved_to_storage_and_listed(make_client, tmp_path):
    _dataset(tmp_path)
    with make_client() as c:
        ds = c.get("/api/evaluation/datasets").json()
        assert ds[0]["id"] == "d" and ds[0]["examples"] == 1
        r = c.post("/api/evaluation/runs", json={"dataset": "d", "mode": "hybrid"})
        assert r.status_code == 202 and r.json()["source"] == "storage"
        run = _wait_run(c, r.json()["id"])
        assert run["status"] == "done" and run["micro_f1"] == 1.0 and run["report"]["docs"] == 1
        assert (tmp_path / "storage" / "evaluations" / run["id"] / "report.json").is_file()
        listed = c.get("/api/evaluation/runs").json()
        assert [x["id"] for x in listed] == [run["id"]]
        docs = c.get(f"/api/evaluation/runs/{run['id']}/documents").json()
        assert docs[0]["f1"] == 1.0 and docs[0]["class_name"] == "demo"
        d = c.get(
            f"/api/evaluation/runs/{run['id']}/documents/{docs[0]['label']}/{docs[0]['stem']}"
        )
        assert d.json()["reference"] == {"nip": "5270000000", "tytul": "Budowa drogi"}


def test_run_validation(make_client, tmp_path):
    _dataset(tmp_path)
    with make_client() as c:
        assert c.post("/api/evaluation/runs", json={"dataset": "nie-ma"}).status_code == 404
        assert c.post("/api/evaluation/runs", json={"dataset": "d", "limit": 0}).status_code == 422
        assert c.post("/api/evaluation/runs", json={"dataset": "d", "mode": "x"}).status_code == 422


def test_failed_run_is_reported_not_raised(make_client, tmp_path):
    from src.llm import LLMError

    _dataset(tmp_path)
    with make_client([LLMError("padło")]) as c:
        run_id = c.post("/api/evaluation/runs", json={"dataset": "d"}).json()["id"]
        run = _wait_run(c, run_id)
        assert (
            run["status"] == "done" and run["errors"] == 1
        )  # awaria dokumentu = errors, nie crash


def test_local_results_are_listed_read_only(make_client, tmp_path):
    results = tmp_path / "results" / "20261121-1"
    (results / "dump-hybrid" / "przyklad_01").mkdir(parents=True)
    report = {
        "docs": 3,
        "micro_f1": 0.9,
        "precision": 0.9,
        "recall": 0.9,
        "errors": 0,
        "citation_ok_rate": 1.0,
        "per_field": {},
        "model": "mm",
        "mode": "hybrid",
    }
    (results / "hybrid.json").write_text(json.dumps(report), encoding="utf-8")
    (results / "summary.json").write_text("[]", encoding="utf-8")
    (results / "dump-hybrid" / "przyklad_01" / "demo.json").write_text(
        json.dumps(
            {
                "class": "demo",
                "prediction": {"nip": "1"},
                "reference": {"nip": "2"},
                "diffs": [],
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    with make_client() as c:
        runs = c.get("/api/evaluation/runs").json()
        assert len(runs) == 1 and runs[0]["source"] == "local" and runs[0]["model"] == "mm"
        run = c.get(f"/api/evaluation/runs/{runs[0]['id']}").json()
        assert run["report"]["micro_f1"] == 0.9
        docs = c.get(f"/api/evaluation/runs/{runs[0]['id']}/documents").json()
        assert docs[0]["stem"] == "demo" and docs[0]["fp"] == 1 and docs[0]["fn"] == 1
        assert c.get(f"/api/evaluation/runs/{runs[0]['id']}/documents/../x/y").status_code == 404
        assert c.get("/api/evaluation/runs/local-nie-ma").status_code == 404


def test_classes_crud_and_validation(client, demo_classes):
    names = [c["name"] for c in client.get("/api/classes").json()]
    assert names == ["demo"]
    r = client.put("/api/classes/nowa", json={"yaml": CLASS_YAML})
    assert r.status_code == 200 and r.json()["fields"][0]["name"] == "numer"
    assert (demo_classes[0] / "nowa.yaml").is_file()
    assert {c["name"] for c in client.get("/api/classes").json()} == {"demo", "nowa"}
    bad = client.put("/api/classes/inna", json={"yaml": CLASS_YAML})
    assert bad.status_code == 422 and "nowa" in bad.json()["detail"]
    assert client.put("/api/classes/x", json={"yaml": "name: [x"}).status_code == 422
    assert client.put("/api/classes/zla", json={"yaml": "name: zla"}).status_code == 422
    assert client.put("/api/classes/..%2Fx", json={"yaml": CLASS_YAML}).status_code in (404, 422)
    assert client.put("/api/classes/Zle-Imie", json={"yaml": CLASS_YAML}).status_code == 422
    assert client.delete("/api/classes/nowa").status_code == 204
    assert client.get("/api/classes/nowa").status_code == 404


def test_new_class_is_used_without_restart(client, pdf_bytes):
    client.put("/api/classes/nowa", json={"yaml": CLASS_YAML})
    from api.conftest import wait_for

    r = client.post("/api/documents", files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))])
    assert wait_for(client, r.json()[0]["id"])["status"] == "done"
