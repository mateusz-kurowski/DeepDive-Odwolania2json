import json

from conftest import classification, extraction

from api.conftest import wait_for


def _upload(client, pdf, name="a.pdf"):
    r = client.post("/api/documents", files=[("files", (name, pdf, "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def test_health_and_settings(client):
    assert client.get("/api/health").json() == {"status": "ok", "storage": "local", "model": "m"}
    s = client.get("/api/settings").json()
    assert s["llm_model"] == "m" and s["storage_backend"] == "local" and "demo" in s["classes"]
    assert "api_key" not in json.dumps(s).lower()


def test_upload_process_and_read_fields(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes)
    doc = wait_for(client, doc_id)
    assert doc["status"] == "done" and doc["class_name"] == "demo"
    assert doc["pages"] >= 1 and doc["field_count"] == 2
    nip = next(f for f in doc["fields"] if f["path"] == "nip")
    assert nip["value"] == "5270000000" and nip["citation_ok"] is True and nip["status"] == "ai"
    assert nip["quote"] == "527-000-00-00" and nip["highlights"] == []
    assert doc["data"] == {"nip": "5270000000", "tytul": "Budowa drogi"}
    assert client.get(f"/api/documents/{doc_id}/pdf").content == pdf_bytes
    png = client.get(f"/api/documents/{doc_id}/pages/1.png?width=400")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{doc_id}/pages/99.png").status_code == 404


def test_upload_rejects_non_pdf_and_oversize(make_client, pdf_bytes):
    with make_client(env={"MAX_UPLOAD_MB": "0"}) as c:
        r = c.post("/api/documents", files=[("files", ("a.pdf", pdf_bytes, "application/pdf"))])
        assert r.status_code == 413 and "MB" in r.json()["detail"]
    with make_client() as c:
        r = c.post("/api/documents", files=[("files", ("a.txt", b"x", "text/plain"))])
        assert r.status_code == 415
        r = c.post("/api/documents", files=[("files", ("a.pdf", b"not pdf", "application/pdf"))])
        assert r.status_code == 415
        assert c.get("/api/documents").json()["items"] == []


def test_failed_document_does_not_block_others(make_client, pdf_bytes):
    from src.llm import LLMError

    responses = [LLMError("model niedostępny")] + [classification(), extraction()]
    with make_client(responses) as c:
        bad = _upload(c, pdf_bytes, "bad.pdf")
        assert wait_for(c, bad)["status"] == "error"
        good = _upload(c, pdf_bytes, "good.pdf")
        assert wait_for(c, good)["status"] == "done"
        assert "model" in c.get(f"/api/documents/{bad}").json()["error"].lower()


def test_patch_field_edit_approve_export(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes)
    wait_for(client, doc_id)
    r = client.patch(f"/api/documents/{doc_id}/fields", json={"path": "tytul", "value": "Nowy"})
    assert r.json()["status"] == "edited" and r.json()["value"] == "Nowy"
    r = client.patch(f"/api/documents/{doc_id}/fields", json={"path": "nip", "status": "approved"})
    assert r.json()["status"] == "approved" and r.json()["value"] == "5270000000"
    assert client.patch(f"/api/documents/{doc_id}/fields", json={"path": "zly"}).status_code == 404
    doc = client.get(f"/api/documents/{doc_id}").json()
    assert doc["approved_count"] == 1 and doc["data"]["tytul"] == "Nowy"
    assert client.post(f"/api/documents/{doc_id}/approve-all").json()["approved_count"] == 2
    out = client.get(f"/api/documents/{doc_id}/export")
    assert out.json() == {"nip": "5270000000", "tytul": "Nowy"}
    assert 'filename="a.json"' in out.headers["content-disposition"]


def test_list_filter_summary_and_bulk_export(client, pdf_bytes):
    a = _upload(client, pdf_bytes, "alfa.pdf")
    b = _upload(client, pdf_bytes, "beta.pdf")
    wait_for(client, a)
    wait_for(client, b)
    listing = client.get("/api/documents", params={"q": "alf"}).json()
    assert [i["filename"] for i in listing["items"]] == ["alfa.pdf"]
    assert listing["summary"]["total"] == 2 and listing["summary"]["processed"] == 2
    assert client.get("/api/documents", params={"status": "error"}).json()["items"] == []
    r = client.post("/api/documents/export", json={"ids": [a, b], "format": "csv"})
    assert r.status_code == 200 and "alfa.pdf" in r.text and "nip" in r.text
    r = client.post("/api/documents/export", json={"ids": [a, b], "format": "jsonl"})
    assert len(r.text.strip().splitlines()) == 2


def test_delete_and_unknown_ids(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes)
    wait_for(client, doc_id)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert client.get("/api/documents/../../etc").status_code == 404
    assert client.get("/api/documents/nie-ma").status_code == 404


def test_reprocess_runs_again(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes)
    wait_for(client, doc_id)
    client.patch(f"/api/documents/{doc_id}/fields", json={"path": "tytul", "value": "X"})
    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 202
    doc = wait_for(client, doc_id)
    assert doc["status"] == "done" and doc["data"]["tytul"] == "Budowa drogi"


def test_samples_endpoint(make_client, tmp_path, pdf_bytes):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "p.pdf").write_bytes(pdf_bytes)
    with make_client(env={"SAMPLES_DIR": str(samples)}) as c:
        r = c.post("/api/documents/samples")
        assert r.status_code == 201 and r.json()[0]["filename"] == "p.pdf"
    with make_client(env={"SAMPLES_DIR": str(tmp_path / "brak")}) as c:
        assert c.post("/api/documents/samples").status_code == 404


def test_revert_restores_model_value_and_unapprove_keeps_edit(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes)
    wait_for(client, doc_id)
    url = f"/api/documents/{doc_id}/fields"
    client.patch(url, json={"path": "tytul", "value": "Nowy"})
    r = client.patch(url, json={"path": "tytul", "status": "approved"}).json()
    assert r["status"] == "approved" and r["value"] == "Nowy"
    r = client.patch(url, json={"path": "tytul", "status": "ai"}).json()
    assert r["status"] == "edited" and r["value"] == "Nowy"
    r = client.patch(url, json={"path": "tytul", "revert": True}).json()
    assert r["status"] == "ai" and r["value"] == "Budowa drogi"
    r = client.patch(url, json={"path": "tytul", "value": "Budowa drogi"}).json()
    assert r["status"] == "ai"
