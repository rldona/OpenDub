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


def test_a_kept_token_survives_a_restart_and_only_its_owner_reads_it(tmp_path, monkeypatch):
    from opendub import cli

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    first = cli.kept_token()
    assert cli.kept_token() == first  # the next start: the same token, so the links still work
    path = tmp_path / "config" / "opendub" / "lan-token"
    assert path.read_text().strip() == first and len(first) >= 24
    assert path.stat().st_mode & 0o777 == 0o600
    path.unlink()  # revoking the links
    assert cli.kept_token() != first


def test_keep_token_needs_lan_and_without_it_the_token_is_new_each_time(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from opendub import cli

    r = CliRunner().invoke(cli.app, ["web", "--keep-token", "--no-browser", "--work", str(tmp_path)])
    assert r.exit_code != 0 and "--keep-token" in r.output
    tokens = []
    monkeypatch.setattr("opendub.web.app.serve", lambda app, port, host: tokens.append(host))
    monkeypatch.setattr("opendub.web.app.create_app", lambda work, token=None: tokens.append(token))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for flags in (["--lan"], ["--lan"], ["--lan", "--keep-token"], ["--lan", "--keep-token"]):
        assert CliRunner().invoke(cli.app, ["web", *flags, "--no-browser", "--work", str(tmp_path)]).exit_code == 0
    made = tokens[0::2]
    assert made[0] != made[1] and made[2] == made[3] == cli.kept_token()
