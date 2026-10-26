"""T-32: the common phase failures carry a code and its parameters, raised where they happen."""

import pytest

from opendub import clone, cosyvoice, diarize, download, indextts, retouch, separate, translate
from opendub.config import Settings
from opendub.errors import CODES, PhaseError
from opendub.workdir import WorkDir


def raised(fn, *args, **kwargs) -> PhaseError:
    with pytest.raises(PhaseError) as e:
        fn(*args, **kwargs)
    return e.value


def test_a_phase_error_is_still_the_cli_s_message_and_checks_its_parameters():
    e = PhaseError("claude_unreachable", "Can't reach Claude", host="api.anthropic.com")
    assert isinstance(e, SystemExit) and str(e) == "Can't reach Claude" and e.params == {"host": "api.anthropic.com"}
    assert e.code == "Can't reach Claude"  # what the CLI prints on exit, not the web's code
    with pytest.raises(ValueError):
        PhaseError("claude_unreachable", "no host")
    with pytest.raises(ValueError):
        PhaseError("made_up", "?")


def test_youtube_blocked_and_unreachable():
    blocked = download.explain(Exception("ERROR: [youtube] x: Sign in to confirm you're not a bot"))
    assert blocked.error_code == "youtube_blocked"
    offline = download.explain(Exception("ERROR: Unable to download webpage: <urlopen error getaddrinfo failed>"))
    assert offline.error_code == "youtube_unreachable"
    other = download.explain(Exception("\x1b[0;31mERROR:\x1b[0m Video unavailable"))
    assert not isinstance(other, PhaseError)  # the rest keeps YouTube's own words, without terminal colours
    assert str(other) == "YouTube download failed: ERROR: Video unavailable"


def test_claude_unreachable(monkeypatch):
    import socket

    def offline(*a, **k):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(translate, "_reachable", None)
    for proxy in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(proxy, raising=False)
    monkeypatch.setattr(socket, "create_connection", offline)
    e = raised(translate.check_claude_reachable)
    assert e.error_code == "claude_unreachable" and e.params == {"host": "api.anthropic.com"}


def test_ollama_unreachable():
    settings = Settings(backend="ollama", ollama_host="http://127.0.0.1:9")  # the discard port: nothing listens
    e = raised(translate._ollama, settings, "/api/chat", {}, 5)
    assert e.error_code == "ollama_unreachable" and e.params == {"host": "http://127.0.0.1:9"}


def test_engines_missing(tmp_path, monkeypatch):
    e = raised(indextts._start, tmp_path / "nowhere", tmp_path / "ix.log")
    assert e.error_code == "engine_missing" and e.params["engine"] == "IndexTTS-2.5"
    assert e.params["cmd"] == "uv run opendub setup-engine indextts"
    e = raised(cosyvoice._start, tmp_path / "nowhere", tmp_path / "cv.log")
    assert e.error_code == "engine_missing" and e.params["cmd"] == "uv run opendub setup-engine cosyvoice"
    import builtins

    real_import = builtins.__import__

    def without(name, *args, **kwargs):
        if name.startswith(("chatterbox", "demucs")):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without)
    monkeypatch.setattr(clone, "_models", {})
    assert raised(clone._load).params == {"engine": "Chatterbox", "cmd": "uv sync --extra clone"}

    def open_separator():
        with separate._separator("torch"):
            pass

    assert raised(open_separator).params["cmd"] == "uv sync --extra separate"


def test_diarizer_missing(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.vocals.parent.mkdir(parents=True, exist_ok=True)
    wd.vocals.write_bytes(b"vocals")
    e = raised(diarize.run, wd, Settings(nemotron_dir=tmp_path / "nowhere"))
    assert e.error_code == "diarizer_missing" and e.params == {"cmd": "uv run opendub setup-engine nemotron"}


def test_clips_deleted(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.tts_index.write_text('{"engine": "chatterbox", "clips": [{"id": 1, "start": 0, "slot": 2, "raw_duration": 1, '
                            '"tempo": 1, "duration": 1, "overflow": 0, "file": "tts/0001.wav"}]}')  # its wav is gone
    wd.translation.write_text("[]")
    assert raised(retouch.retouch, wd, Settings()).error_code == "clips_deleted"


def test_every_code_is_tested_here():
    import inspect
    import sys

    source = inspect.getsource(sys.modules[__name__])
    assert all(f'"{code}"' in source for code in CODES)
