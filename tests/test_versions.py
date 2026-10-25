"""Every dub kept as a version, and hand edits surviving a translation made again."""
import json

from opendub import mix, translate
from opendub.models import Segment, load_segments, save_segments
from opendub.tts import Pace
from opendub.workdir import WorkDir


def _dub(wd, engine, content):
    tmp = wd.path / "output.part.mp4"
    tmp.write_bytes(content)
    tmp.replace(wd.output)  # as mix.run writes it: a new file each time
    wd.tts_index.write_text(json.dumps({"engine": engine, "clips": []}))
    return mix.archive(wd)


def test_every_dub_is_kept(tmp_path, monkeypatch):
    from datetime import datetime

    times = iter(datetime(2026, 10, 25, 11, m) for m in range(10))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(mix, "datetime", Clock)
    wd = WorkDir(tmp_path, "vid")
    first = _dub(wd, "chatterbox", b"chatterbox dub")
    assert first == wd.outputs_dir / "20261025-110000-chatterbox.mp4" and first.samefile(wd.output)  # hard link
    assert mix.archive(wd) == first  # a cached mix is not kept twice
    _dub(wd, "indextts", b"indextts dub")
    _dub(wd, "chatterbox", b"chatterbox again")  # the same engine again: the first one stays
    kept = {p.name: p.read_bytes() for p in wd.outputs_dir.glob("*.mp4")}
    assert kept == {"20261025-110000-chatterbox.mp4": b"chatterbox dub", "20261025-110100-indextts.mp4": b"indextts dub",
                    "20261025-110200-chatterbox.mp4": b"chatterbox again"}
    assert (wd.outputs_dir / "20261025-110100-indextts.tts.json").exists()
    assert wd.output.read_bytes() == b"chatterbox again"


def test_hand_edits_survive_a_new_translation(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    originals = [Segment(1, 0.0, 2.0, "Hello."), Segment(2, 3.0, 5.0, "Bye."), Segment(3, 6.0, 7.0, "Changed.")]
    wd.translation_edits.write_text(json.dumps({
        "1": {"source": "Hello.", "text": "¡Hola, qué tal!"},
        "3": {"source": "Something else.", "text": "Ya no corresponde."},  # its original changed
        "2": {"source": "Bye.", "text": "Adiós, y muchas gracias por quedaros hasta el final del vídeo."},
    }))
    fresh = [Segment(1, 0.0, 2.0, "Hola."), Segment(2, 3.0, 5.0, "Adiós."), Segment(3, 6.0, 7.0, "Cambiado.")]
    out = translate.keep_edits(wd, originals, fresh, Pace(15.0))
    assert [s.text for s in out] == ["¡Hola, qué tal!", "Adiós, y muchas gracias por quedaros hasta el final del vídeo.",
                                     "Cambiado."]
    assert set(json.loads(wd.translation_edits.read_text())) == {"1", "2"}  # the misplaced one is forgotten


def test_web_saves_edits_and_lists_versions(tmp_path):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from opendub.web.app import create_app

    work = tmp_path / "work"
    wd = WorkDir(work, "17kBVfGjI8c")
    wd.meta.write_text(json.dumps({"title": "t", "duration": 10}))
    save_segments(wd.segments, [Segment(1, 0.0, 2.0, "Hello.")])
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "Hola.")])
    _dub(wd, "chatterbox", b"c" * 64)
    _dub(wd, "indextts", b"i" * 64)
    wd.mark_done("mix", {})
    c = TestClient(create_app(work, runner=lambda url, s: None, allowed_hosts=("testserver",)))
    c.put("/videos/17kBVfGjI8c/translation", json=[{"id": 1, "text": "¡Hola!"}])
    assert json.loads(wd.translation_edits.read_text()) == {"1": {"source": "Hello.", "text": "¡Hola!"}}
    assert c.get("/videos/17kBVfGjI8c/translation").json()["segments"][0]["edited"] is True
    (wd.outputs_dir / "cosyvoice.mp4").write_bytes(b"o" * 64)  # kept before versions had dates (one per engine)
    versions = c.get("/videos/17kBVfGjI8c").json()["outputs"]
    assert sorted(v["engine"] for v in versions) == ["chatterbox", "cosyvoice", "indextts"]
    assert [v["engine"] for v in versions if v["current"]] == ["indextts"]
    chatterbox = next(v["version"] for v in versions if v["engine"] == "chatterbox")
    r = c.get(f"/videos/17kBVfGjI8c/outputs/{chatterbox}.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == b"c" * 10
    assert c.get("/videos/17kBVfGjI8c/outputs/cosyvoice.mp4").content == b"o" * 64
    assert c.get("/videos/17kBVfGjI8c/outputs/..%2Fmeta.mp4").status_code == 404


def test_web_deletes_old_versions_but_not_the_latest(tmp_path):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from opendub.web.app import create_app

    work = tmp_path / "work"
    wd = WorkDir(work, "17kBVfGjI8c")
    wd.meta.write_text(json.dumps({"title": "t", "duration": 10}))
    old = _dub(wd, "chatterbox", b"c" * 64)
    wd.overflow_log.write_text("x")
    latest = _dub(wd, "indextts", b"i" * 64)
    c = TestClient(create_app(work, runner=lambda url, s: None, allowed_hosts=("testserver",)))
    assert c.delete(f"/videos/17kBVfGjI8c/outputs/{latest.stem}").status_code == 409
    r = c.delete(f"/videos/17kBVfGjI8c/outputs/{old.stem}")
    assert r.status_code == 200 and [v["version"] for v in r.json()["outputs"]] == [latest.stem]
    assert not any(wd.outputs_dir.glob(f"{old.stem}.*")) and wd.output.read_bytes() == b"i" * 64
    assert c.delete(f"/videos/17kBVfGjI8c/outputs/{old.stem}").status_code == 404
    assert c.delete("/videos/17kBVfGjI8c/outputs/..%2Fmeta").status_code == 404
