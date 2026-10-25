"""Exports of a kept dub (export.py): subtitles, MKV with both audio tracks, the dubbed audio."""

import json
import shutil
import subprocess

import pytest

from opendub import export
from opendub.media import probe
from opendub.models import Segment, save_segments
from opendub.workdir import WorkDir


def _clip(i, start, duration, text):
    return {"id": i, "start": start, "slot": 3.0, "raw_duration": duration, "tempo": 1.0, "duration": duration,
            "overflow": 0.0, "file": f"tts/{i:04d}.wav", "text": text, "voice": "chatterbox", "factor": 1.0}


@pytest.fixture
def wd(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"language": "en", "duration": 6.0}))
    save_segments(wd.segments, [Segment(1, 0.5, 2.0, "Hello there."), Segment(2, 2.5, 4.0, "How are you?")])
    wd.outputs_dir.mkdir()
    index = {"engine": "chatterbox", "clips": [_clip(1, 0.5, 2.4, "Hola, ¿qué tal?"), _clip(2, 2.5, 1.0, "¿Cómo estás?")]}
    (wd.outputs_dir / "20261025-101010-chatterbox.tts.json").write_text(json.dumps(index))
    return wd


def _media(path, seconds=6):
    """A tiny h264 + aac mp4, as yt-dlp and the mix leave them."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s=64x64:d={seconds}", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)], check=True)


def test_srt_follows_the_mix_and_splits_long_cues(wd):
    srt = export.dubbed_srt(export._clips(wd.outputs_dir / "20261025-101010-chatterbox.tts.json"))
    # clip 1 lasts 2.4 s from 0.5 s: clip 2 is pushed to 2.98 s (2.9 + the mix's 0.08 s gap)
    assert srt.splitlines()[1] == "00:00:00,500 --> 00:00:02,900"
    assert "00:00:02,980 --> 00:00:03,980" in srt
    cues = export._split(0.0, 10.0, "palabra " * 30)
    assert len(cues) == 3 and all(len(lines) <= 2 for _, _, lines in cues)
    assert cues[0][0] == 0.0 and cues[-1][1] == pytest.approx(10.0)
    assert export._time(3725.5) == "01:02:05,500"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_latest_is_the_version_output_mp4_is(wd):
    with pytest.raises(LookupError):
        export.version_stem(wd)
    _media(wd.outputs_dir / "20261025-101010-chatterbox.mp4")
    wd.output.hardlink_to(wd.outputs_dir / "20261025-101010-chatterbox.mp4")  # as mix.archive keeps it
    assert export.version_stem(wd) == export.version_stem(wd, "latest") == "20261025-101010-chatterbox"
    with pytest.raises(LookupError):
        export.version_stem(wd, "../meta")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_mkv_has_both_audio_tracks_and_both_subtitles(wd):
    stem = "20261025-101010-chatterbox"
    _media(wd.outputs_dir / f"{stem}.mp4")
    _media(wd.video)
    mkv = export.export(wd, "mkv", stem)
    streams = probe(mkv)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "audio", "audio", "subtitle", "subtitle"]
    assert [s["tags"].get("language") for s in streams[1:]] == ["spa", "eng", "spa", "eng"]
    assert streams[1]["disposition"]["default"] == 1 and streams[2]["disposition"]["default"] == 0
    m4a = export.export(wd, "m4a", stem)
    assert [s["codec_type"] for s in probe(m4a)["streams"]] == ["audio"]
    assert export.export(wd, "mkv", stem).stat().st_mtime == mkv.stat().st_mtime  # kept, not made again
    with pytest.raises(ValueError):
        export.export(wd, "avi", stem)
