"""The blind listening tools (docs/bench/listening): the same seed, the same session; answers per engine."""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "docs" / "bench" / "listening"))
import session  # noqa: E402
import summary  # noqa: E402


@pytest.fixture
def work(tmp_path, monkeypatch):
    vid = tmp_path / "abcdefghijk"
    vid.mkdir()
    segs = [{"id": i + 1, "start": i * 4.0, "end": i * 4.0 + 3.5, "text": f"s{i}"} for i in range(60)]
    (vid / "segments.json").write_text(json.dumps(segs))
    monkeypatch.setattr(session, "WORK", tmp_path)
    return tmp_path


def test_fragments_last_10_to_15_s_and_a_seed_makes_them_again(work):
    assert all(10 <= end - start <= 15 for start, end in session.windows("abcdefghijk"))
    first = session.pick("abcdefghijk", 4, random.Random(7))
    assert session.pick("abcdefghijk", 4, random.Random(7)) == first
    assert len(first) == 4 and first == sorted(first)  # one in each quarter of the video
    for seed in range(30):  # no stretch is heard twice, even where a window runs into the next part
        picked = session.pick("abcdefghijk", 6, random.Random(seed))
        assert all(a[1] <= b[0] for a, b in zip(picked, picked[1:]))


def test_a_version_can_be_named_instead_of_an_engine(work):
    out = work / "abcdefghijk" / "outputs"
    out.mkdir()
    for v in ("20261025-100000-chatterbox", "20261025-110000-chatterbox"):
        (out / f"{v}.mp4").touch()
    assert session.latest("abcdefghijk", "chatterbox") == "20261025-110000-chatterbox"
    assert session.latest("abcdefghijk", "20261025-100000-chatterbox") == "20261025-100000-chatterbox"
    with pytest.raises(SystemExit):
        session.latest("abcdefghijk", "indextts")


def test_answers_are_given_back_per_engine():
    s = {"a": "chatterbox", "b": "chatterbox-es", "fragments": [
        {"id": "f01", "video": "v", "start": 1.0, "end": 12.0, "versions": {"a": "x-chatterbox", "b": "y-chatterbox-es"},
         "order": {"1": "b", "2": "a"}}]}
    data = {"answers": {"f01": {"ratings": {"1": {"naturalness": 5, "meaning": 4, "sync": 4},
                                            "2": {"naturalness": 3, "meaning": 4, "sync": 3}}, "prefer": "1"}}}
    r = session.reveal(s, data)["f01"]
    assert r["ratings"]["chatterbox-es"]["naturalness"] == 5 and r["ratings"]["chatterbox"]["naturalness"] == 3
    assert r["prefer"] == "chatterbox-es"
    total = summary.summarize({"name": "t", "a": "chatterbox", "b": "chatterbox-es", "revealed": {"f01": r}})
    assert total["means"]["chatterbox-es"]["naturalness"] == 5 and total["prefer"]["chatterbox-es"] == 1


def _media(path, seconds, video=True):
    import subprocess

    inputs = ["-f", "lavfi", "-i", f"sine=f=330:d={seconds}"]
    if video:
        inputs = ["-f", "lavfi", "-i", f"color=c=gray:s=64x64:d={seconds}", *inputs, "-c:v", "libx264", "-shortest"]
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, str(path)], check=True)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_a_session_sets_opendub_against_dubs_made_with_other_tools(work, tmp_path, monkeypatch):
    vid = work / "abcdefghijk"
    _media(vid / "video.mp4", 240)  # 60 sentences of 4 s
    _media(vid / "outputs" / "20261025-100000-chatterbox.mp4", 240)
    _media(tmp_path / "se" / "abcdefghijk.mp4", 240)  # another tool's dubbed video
    _media(tmp_path / "el" / "abcdefghijk.m4a", 240, video=False)  # another tool's dubbed audio alone
    monkeypatch.setattr(session, "OUT", tmp_path / "sessions")
    monkeypatch.setattr(session, "RESULTS", tmp_path / "results")
    sources = {"opendub": "chatterbox", "subtitle-edit": f"file:{tmp_path}/se/{{video}}.mp4",
               "elevenlabs": f"file:{tmp_path}/el/{{video}}.m4a"}
    session.make("three", sources, ["abcdefghijk"], 2, 1)
    s = json.loads((tmp_path / "sessions" / "three" / "session.json").read_text())
    assert s["criteria"] == ["overall"] and session.labels(s) == {"a": "opendub", "b": "subtitle-edit",
                                                                  "c": "elevenlabs"}
    for f in s["fragments"]:
        assert sorted(f["order"]) == ["1", "2", "3"] and sorted(f["order"].values()) == ["a", "b", "c"]
        for side in f["order"]:  # every dub with a picture, the audio-only one with the original's
            kinds = __import__("subprocess").run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                 str(tmp_path / "sessions" / "three" / "media" / f"{f['id']}_{side}.mp4")],
                capture_output=True, text=True).stdout.split()
            assert sorted(kinds) == ["audio", "video"]
    f = s["fragments"][0]
    side_of = {key: side for side, key in f["order"].items()}
    answer = {"ratings": {side: {"overall": 2} for side in f["order"]}, "prefer": side_of["c"]}
    answer["ratings"][side_of["a"]] = {"overall": 5}
    assert not session.complete(s, f, {"ratings": {"1": {"overall": 3}}, "prefer": "1"})  # a dub left unrated
    assert session.complete(s, f, answer)
    r = session.reveal(s, {"answers": {f["id"]: answer}})[f["id"]]
    assert r["ratings"]["opendub"] == {"overall": 5} and r["prefer"] == "elevenlabs"
    total = summary.summarize({**session.results(s), "revealed": {f["id"]: r}})
    assert total["means"]["opendub"]["overall"] == 5 and total["prefer"]["elevenlabs"] == 1


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_a_dub_not_on_the_video_timeline_is_refused(work, tmp_path, monkeypatch):
    vid = work / "abcdefghijk"
    _media(vid / "video.mp4", 240)
    _media(vid / "outputs" / "20261025-100000-chatterbox.mp4", 240)
    _media(tmp_path / "short.m4a", 200, video=False)  # a dub of only part of the video
    monkeypatch.setattr(session, "OUT", tmp_path / "sessions")
    with pytest.raises(SystemExit, match="not a dub of the whole video"):
        session.make("bad", {"opendub": "chatterbox", "other": f"file:{tmp_path}/short.m4a"}, ["abcdefghijk"], 2, 1)
    with pytest.raises(SystemExit, match="does not exist"):
        session.make("bad", {"opendub": "chatterbox", "other": "file:nowhere/{video}.mp4"}, ["abcdefghijk"], 2, 1)
