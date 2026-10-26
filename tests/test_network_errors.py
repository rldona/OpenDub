"""Without a connection, or when YouTube blocks the download, each service fails with a clear message."""

import asyncio
import json

import pytest

from opendub import download, translate, tts
from opendub.config import Settings
from opendub.workdir import WorkDir


def test_edge_tts_unreachable_says_so(monkeypatch):
    import edge_tts

    async def offline():
        raise OSError("Network is unreachable")

    monkeypatch.setattr(edge_tts, "list_voices", offline)
    with pytest.raises(SystemExit, match="Can't reach edge-tts.*internet connection"):
        asyncio.run(tts._check_voice("es-ES-AlvaroNeural"))


def test_edge_tts_check_has_a_time_limit(monkeypatch):
    import edge_tts

    async def hangs():
        await asyncio.sleep(10)

    monkeypatch.setattr(edge_tts, "list_voices", hangs)
    monkeypatch.setattr(tts, "CHECK_VOICE_TIMEOUT_S", 0.05)
    with pytest.raises(SystemExit, match="TimeoutError"):
        asyncio.run(tts._check_voice("es-ES-AlvaroNeural"))


@pytest.mark.parametrize("message, expected", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies…", "temporary block"),
    ("ERROR: Unable to download API page: [Errno -3] Temporary failure in name resolution", "internet connection"),
    ("ERROR: [youtube] abc: Video unavailable", "YouTube download failed: ERROR: \\[youtube\\] abc: Video unavailable"),
])
def test_youtube_failures_are_explained(tmp_path, monkeypatch, message, expected):
    import yt_dlp

    class Failing:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, *a, **k):
            raise yt_dlp.utils.DownloadError(message)

        def sanitize_info(self, info):
            return info

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Failing)
    with pytest.raises(SystemExit, match=expected):
        download.run("dQw4w9WgXcQ", WorkDir(tmp_path, "dQw4w9WgXcQ"), Settings(work_root=tmp_path))


def test_claude_failing_every_attempt_says_why(monkeypatch):
    calls = []

    def failing(system, prompt, model):
        calls.append(1)
        raise RuntimeError("claude returned an error: network unreachable")

    monkeypatch.setattr(translate, "_call_cli", failing)
    with pytest.raises(SystemExit, match="after 3 attempts: claude returned an error: network unreachable"):
        translate._ask("s", json.dumps({}), [1], Settings())
    assert len(calls) == translate.MAX_ATTEMPTS  # no endless retries


def test_claude_api_unreachable_is_a_clear_error(monkeypatch):
    import anthropic
    import httpx

    def offline(client, model, system, prompt):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    monkeypatch.setattr(translate, "_create", offline)
    with pytest.raises(SystemExit, match="can't reach the Claude API"):
        translate._ask("s", "{}", [1], Settings(backend="api", anthropic_api_key="test-key"))


def test_claude_unreachable_fails_at_once(monkeypatch):
    import socket

    monkeypatch.setattr(translate, "_reachable", None)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError("unreachable")))
    monkeypatch.setattr(translate, "_call_cli", lambda *a: pytest.fail("no attempt without a connection"))
    with pytest.raises(SystemExit, match="Can't reach Claude"):
        translate._ask("s", "{}", [1], Settings())


@pytest.mark.parametrize("spec, expected", [
    ("firefox", ("firefox", None, None, None)),
    ("Chrome:Profile 1", ("chrome", "Profile 1", None, None)),
    ("chromium+gnomekeyring:Default", ("chromium", "Default", "GNOMEKEYRING", None)),
    ("firefox::Personal", ("firefox", None, None, "Personal")),
])
def test_cookies_from_browser_take_yt_dlp_s_syntax(spec, expected):
    assert download.cookies_option(spec) == {"cookiesfrombrowser": expected}
    assert download.cookies_option(None) == {}


def test_an_unknown_browser_is_refused_before_downloading():
    with pytest.raises(SystemExit, match="give a browser"):
        download.cookies_option("netscape")


def test_every_youtube_request_goes_with_the_browser_s_cookies(tmp_path, monkeypatch):
    """--cookies-from-browser, or OPENDUB_COOKIES_FROM_BROWSER for the web: the info, the media,
    the subtitles and the thumbnail are all asked for as that session."""
    import yt_dlp

    seen = []

    class Recording:
        def __init__(self, opts):
            seen.append(opts.get("cookiesfrombrowser"))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, *a, **k):
            raise yt_dlp.utils.DownloadError("ERROR: Sign in to confirm you're not a bot")

        def sanitize_info(self, info):
            return info

        def download(self, urls):
            pass

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Recording)
    settings = Settings(work_root=tmp_path, cookies_from_browser="firefox")
    with pytest.raises(SystemExit, match="--cookies-from-browser"):  # the bot check says what to try
        download.run("dQw4w9WgXcQ", WorkDir(tmp_path, "dQw4w9WgXcQ"), settings)
    download.thumbnail(WorkDir(tmp_path, "dQw4w9WgXcQ"), settings)
    assert seen == [("firefox", None, None, None)] * 2
    monkeypatch.setenv("OPENDUB_COOKIES_FROM_BROWSER", "chrome")
    assert Settings().cookies_from_browser == "chrome"  # the web page's default
    monkeypatch.delenv("OPENDUB_COOKIES_FROM_BROWSER")
    assert Settings().cookies_from_browser is None
