"""opendub web --lan: any host name, but nothing without the token (create_app(token=...))."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from test_web import VID, FakePipeline, make_video  # noqa: E402

from opendub.web.app import COOKIE, create_app  # noqa: E402

TOKEN = "s3cret-token-for-tests"


def lan_client(tmp_path, **kw):
    return TestClient(create_app(tmp_path / "work", runner=FakePipeline(), token=TOKEN),
                      base_url="http://192.168.1.20:8000", **kw)


def test_without_the_token_everything_is_401_but_the_entry_page(tmp_path):
    make_video(tmp_path / "work")
    c = lan_client(tmp_path)
    entry = c.get("/")
    assert entry.status_code == 200 and "token" in entry.text and "<script" not in entry.text
    for method, path in (("get", "/status"), ("get", "/videos"), ("get", f"/videos/{VID}/translation"),
                         ("get", "/static/index.html"), ("post", "/jobs"), ("get", f"/videos/{VID}/thumbnail"),
                         ("delete", f"/videos/{VID}/storage/stems")):
        r = getattr(c, method)(path)
        assert r.status_code == 401, (method, path)
        assert r.json()["detail"]["code"] == "unauthorized"
    assert c.get("/?token=wrong").status_code == 401
    c.cookies.set(COOKIE, "wrong")
    assert c.get("/status").status_code == 401


def test_the_link_leaves_a_cookie_and_the_token_out_of_the_address(tmp_path):
    c = lan_client(tmp_path, follow_redirects=False)
    r = c.get(f"/?token={TOKEN}")
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}={TOKEN}" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert c.get("/status").status_code == 200  # the cookie is sent from now on
    assert c.get("/").status_code == 200 and "<script" in c.get("/").text  # the real page
    other = lan_client(tmp_path)
    assert other.get("/status", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_the_local_mode_is_as_it_was(tmp_path):
    c = TestClient(create_app(tmp_path / "work", runner=FakePipeline()), base_url="http://127.0.0.1:8000")
    assert c.get("/status").status_code == 200  # no token asked for
    lan_name = TestClient(create_app(tmp_path / "work", runner=FakePipeline()), base_url="http://192.168.1.20:8000")
    assert lan_name.get("/status").status_code == 400  # other host names are still refused (DNS rebinding)


def test_the_cli_starts_on_every_interface_only_with_lan(tmp_path, monkeypatch, caplog):
    from typer.testing import CliRunner

    from opendub import cli
    from opendub.web import app as web_app

    started = []
    monkeypatch.setattr(web_app, "serve", lambda app, port, host="127.0.0.1": started.append(
        (host, app.user_middleware)))
    monkeypatch.setattr(cli, "require_ffmpeg", lambda: None)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["web", "--work", str(tmp_path), "--no-browser"]).exit_code == 0
    r = runner.invoke(cli.app, ["web", "--work", str(tmp_path), "--no-browser", "--lan"])
    assert r.exit_code == 0 and "another device:  http://" in r.output and "?token=" in r.output
    assert all(len(line) < 200 for line in r.output.splitlines())  # each link whole on its own line
    assert [h for h, _ in started] == ["127.0.0.1", "0.0.0.0"]
