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


def test_each_version_has_its_own_issues_and_numbers(tmp_path):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from opendub.web.app import create_app

    work = tmp_path / "work"
    wd = WorkDir(work, "17kBVfGjI8c")
    wd.meta.write_text(json.dumps({"title": "t", "duration": 10}))
    clip = {"start": 1.0, "slot": 2.0, "raw_duration": 1.5, "duration": 1.5, "overflow": 0.0, "file": "tts/0001.wav",
            "text": "Hola.", "factor": 1.0}

    def dub(engine, content, clips, log, stats=None):
        tmp = wd.path / "output.part.mp4"
        tmp.write_bytes(content)
        tmp.replace(wd.output)
        wd.tts_index.write_text(json.dumps({"engine": engine, "stats": stats or {}, "clips": clips}))
        wd.overflow_log.write_text(log)
        return mix.archive(wd)

    old = dub("cosyvoice", b"c" * 64, [{**clip, "id": 1, "tempo": 1.0, "voice": "edge"},
                                       {**clip, "id": 2, "tempo": 1.0, "voice": "cosyvoice (seed+1)"}],
              "#1 @1.00s: cloned voice failed the quality check, used edge-tts · Hola.\n")
    dub("indextts", b"i" * 64, [{**clip, "id": 1, "tempo": 1.2, "voice": "indextts"},
                                {**clip, "id": 2, "tempo": 1.0, "voice": "indextts"}],
        "#2 @1.00s: did not fit even shortened, duration factor 0.62 below the 0.70 floor · Hola.\n",
        stats={"seconds": 42.5, "shortened": 3})
    c = TestClient(create_app(work, runner=lambda url, s: None, allowed_hosts=("testserver",)))
    outputs = c.get("/videos/17kBVfGjI8c").json()["outputs"]
    assert [(o["engine"], o["issues"]) for o in outputs] == [("indextts", 1), ("cosyvoice", 2)]

    latest = c.get("/videos/17kBVfGjI8c/versions/latest").json()
    assert latest["current"] and latest["engine"] == "indextts"
    assert latest["stats"] == {"clips": 2, "voice_seconds": 42.5, "sped_up": 1, "shortened": 3, "below_floor": 1,
                               "redone": 0, "edge": 0}
    older = c.get(f"/videos/17kBVfGjI8c/versions/{old.stem}").json()
    assert not older["current"] and older["stats"]["edge"] == 1 and older["stats"]["redone"] == 1
    assert {i["kind"] for i in older["issues"]} == {"fallback", "repaired"}
    assert all(i["wav"] is None for i in older["issues"])  # its clips are gone: heard by seeking its video
    assert [i["kind"] for i in c.get(f"/videos/17kBVfGjI8c/issues?version={old.stem}").json()] == ["fallback", "repaired"]
    assert c.get("/videos/17kBVfGjI8c/versions/nope").status_code == 404
