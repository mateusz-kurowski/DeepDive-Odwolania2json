"""`python -m src gui`: API serwuje statyczny front z WEB_DIR (tryb bez Dockera)."""


def test_web_dir_serves_frontend_and_keeps_api(make_client, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>front</title>", encoding="utf-8")
    with make_client(env={"WEB_DIR": str(web)}) as c:
        assert "front" in c.get("/").text
        assert c.get("/api/health").json()["status"] == "ok"


def test_without_web_dir_root_is_not_served(client):
    assert client.get("/").status_code == 404
