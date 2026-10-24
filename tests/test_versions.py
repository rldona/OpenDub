"""One dub kept per engine, and hand edits surviving a translation made again."""
import json

from opentranslator import mix, translate
from opentranslator.models import Segment, load_segments, save_segments
from opentranslator.tts import Pace
from opentranslator.workdir import WorkDir


def _dub(wd, engine, content):
    tmp = wd.path / "output.part.mp4"
    tmp.write_bytes(content)
    tmp.replace(wd.output)  # as mix.run writes it: a new file each time
    wd.tts_index.write_text(json.dumps({"engine": engine, "clips": []}))
    return mix.archive(wd)


def test_each_engine_keeps_its_own_dub(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    first = _dub(wd, "chatterbox", b"chatterbox dub")
    assert first == wd.outputs_dir / "chatterbox.mp4" and first.samefile(wd.output)  # hard link, no copy
    _dub(wd, "indextts", b"indextts dub")
    assert (wd.outputs_dir / "chatterbox.mp4").read_bytes() == b"chatterbox dub"  # untouched by the new mix
    assert (wd.outputs_dir / "indextts.mp4").read_bytes() == b"indextts dub" == wd.output.read_bytes()
    assert (wd.outputs_dir / "indextts.tts.json").exists()
    _dub(wd, "chatterbox", b"chatterbox again")
    assert (wd.outputs_dir / "chatterbox.mp4").read_bytes() == b"chatterbox again"


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

    from opentranslator.web.app import create_app

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
    versions = c.get("/videos/17kBVfGjI8c").json()["outputs"]
    assert {v["engine"] for v in versions} == {"chatterbox", "indextts"}
    assert [v["engine"] for v in versions if v["current"]] == ["indextts"]
    r = c.get("/videos/17kBVfGjI8c/outputs/chatterbox.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == b"c" * 10
    assert c.get("/videos/17kBVfGjI8c/outputs/..%2Fmeta.mp4").status_code == 404
