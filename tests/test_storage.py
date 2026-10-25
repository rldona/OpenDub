"""Freeing a video's disk space (storage.py), and each phase making again what it needs."""

import json

import pytest

from opendub import download, retouch, storage, tts
from opendub.config import Settings
from opendub.workdir import WorkDir


def _video(tmp_path):
    wd = WorkDir(tmp_path, "abcdefghijk")
    wd.meta.write_text(json.dumps({"id": "abcdefghijk", "title": "t", "duration": 5}))
    for path, size in [(wd.video, 4000), (wd.audio, 1000), (wd.vocals, 3000), (wd.background, 3000),
                       (wd.tts_dir / "raw" / "a1.wav", 500), (wd.tts_dir / "raw" / "b2.wav", 500),
                       (wd.tts_dir / "0001.wav", 200), (wd.outputs_dir / "20261025-101010-edge.mp4", 9000),
                       (wd.outputs_dir / "20261025-101010-edge.mkv", 8000), (wd.outputs_dir / "20261025-101010-edge.es.srt", 50)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return wd


def test_usage_by_group_and_what_always_stays(tmp_path):
    wd = _video(tmp_path)
    sizes = {g["id"]: g["bytes"] for g in storage.usage(wd)["groups"]}
    assert sizes == {"source": 5000, "stems": 6000, "raw": 1000, "clips": 200, "exports": 8050}
    assert storage.usage(wd)["kept"] >= 9000  # the version stays
    assert storage.delete(wd, "exports") == 8050
    assert (wd.outputs_dir / "20261025-101010-edge.mp4").exists()  # only the exports went
    for group in ("source", "stems", "raw", "clips"):
        storage.delete(wd, group)
    assert all(g["bytes"] == 0 for g in storage.usage(wd)["groups"])
    with pytest.raises(KeyError):
        storage.delete(wd, "outputs")


def test_the_download_brings_back_only_the_media(tmp_path, monkeypatch):
    wd = _video(tmp_path)
    wd.mark_done("download", {"max_height": 1080, "source_lang": None})
    wd.mark_done("transcribe", {"x": 1})
    storage.delete(wd, "source")
    fetched = []
    monkeypatch.setattr(download, "_info", lambda url: {"id": "abcdefghijk"})
    monkeypatch.setattr(download, "_fetch_media", lambda raw, wd_, s: fetched.append(raw["id"]))
    download.run("abcdefghijk", wd, Settings(work_root=tmp_path))
    assert fetched == ["abcdefghijk"] and wd.has("transcribe")  # nothing after it is invalidated


def test_retouching_needs_the_clips_and_a_dub_speaks_them_again(tmp_path, monkeypatch):
    from opendub.models import Segment, save_segments

    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"duration": 10.0}))
    save_segments(wd.segments, [Segment(1, 0.0, 2.0, "Hello.")])
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "Hola.")])
    spoken = []

    def fake_render(wd_, jobs, slots, settings, regenerate=False):
        out = []
        for seg, _voice in jobs:
            spoken.append(seg.id)
            (wd_.tts_dir).mkdir(exist_ok=True)
            (wd_.tts_dir / f"{seg.id:04d}.wav").write_bytes(b"")
            out.append(tts.Clip(seg.id, seg.start, 3.0, 1.0, 1.0, 1.0, 0.0, f"tts/{seg.id:04d}.wav", seg.text))
        return out

    async def no_check(voice):
        return None

    monkeypatch.setattr(tts, "_render_jobs", fake_render)
    monkeypatch.setattr(tts, "_check_voice", no_check)
    tts.run(wd, Settings())
    storage.delete(wd, "clips")
    with pytest.raises(SystemExit, match="deleted to save space"):
        retouch.retouch(wd, Settings(), [])
    spoken.clear()
    tts.run(wd, Settings())  # cached by its parameters, but its clips are gone: spoken again
    assert spoken == [1] and tts.clips_exist(wd)


pytest.importorskip("fastapi")
from test_web import VID, FakePipeline, client, make_video  # noqa: E402


def test_the_web_frees_space_and_says_what_stays(tmp_path):
    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    usage = c.get(f"/videos/{VID}/storage").json()
    assert {g["id"] for g in usage["groups"]} == set(storage.GROUPS)
    assert next(g for g in usage["groups"] if g["id"] == "clips")["files"] == 3
    r = c.delete(f"/videos/{VID}/storage/clips")
    assert r.status_code == 200 and r.json()["freed"] > 0
    assert c.get(f"/videos/{VID}/translation").json()["clips_available"] is False
    assert c.delete(f"/videos/{VID}/storage/everything").status_code == 404
    with wd.lock("opendub dub"):
        assert c.delete(f"/videos/{VID}/storage/raw").status_code == 409


def test_the_mkv_needs_the_original_video(tmp_path):
    c = client(tmp_path, FakePipeline())
    wd = make_video(tmp_path / "work")
    wd.outputs_dir.mkdir()
    (wd.outputs_dir / "20261024-090000-edge.mp4").write_bytes(b"x")
    (wd.outputs_dir / "20261024-090000-edge.tts.json").write_text(wd.tts_index.read_text())
    r = c.get(f"/videos/{VID}/outputs/20261024-090000-edge/export/mkv")
    assert r.status_code == 409 and "deleted to save space" in r.json()["detail"]["message"]
