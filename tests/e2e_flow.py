"""A whole dub without network or GPU, shared by test_e2e.py and the macOS CI check.

A synthetic 12 s video with local subtitles stands for the download; the translation
and the voice are fakes (the voice writes real wavs); everything else runs for real:
transcription from the subtitles, translation's caching, ffmpeg trimming and atempo,
the mix with its loudness normalization, the kept version and the exports.
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import wave
from pathlib import Path

VID = "abcdefghijk"
VTT = """WEBVTT

00:00:00.500 --> 00:00:02.500
Hello there, this is a test.

00:00:03.000 --> 00:00:05.500
We are dubbing a short video.

00:00:06.500 --> 00:00:09.000
It has four sentences in all.

00:00:09.500 --> 00:00:11.500
Thanks for listening.
"""


def make_video(work: Path) -> Path:
    """The work folder a download would leave: video, audio, subtitles, meta and the manifest entry."""
    from opendub.workdir import WorkDir

    wd = WorkDir(work, VID)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=12",
                    "-f", "lavfi", "-i", "sine=f=220:d=12", "-af", "volume=-25dB", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(wd.video)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wd.video), "-vn", "-ac", "1", "-ar", "16000",
                    str(wd.audio)], check=True)
    (wd.path / "subs.manual.vtt").write_text(VTT)
    wd.meta.write_text(json.dumps({"id": VID, "title": "Test", "duration": 12, "uploader": "me", "language": "en",
                                   "subs": {"manual": "subs.manual.vtt", "auto": None}}))
    wd.mark_done("download", {"max_height": 1080, "source_lang": None})
    return wd.path


def _tone(path: Path, seconds: float) -> None:
    n = int(24000 * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack(f"<{n}h", *(int(4000 * math.sin(2 * math.pi * 300 * i / 24000)) for i in range(n))))


def install_fakes(setattr) -> None:
    """Replace the network parts: `setattr(obj, name, value)` (pytest's monkeypatch.setattr, or plain setattr)."""
    from opendub import translate, tts

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        return {"segments": [{"id": s["id"], "text": f"Frase número {s['id']}."} for s in data["segments"]]}, 0.0

    def fake_voice(jobs, settings):
        for text, path, _voice in jobs:  # about 14 chars/s, like a real voice
            _tone(path, max(0.4, len(text) / 14))

    async def no_check(voice):
        return None

    setattr(translate, "_call_cli", fake_cli)
    setattr(translate, "_reachable", True)
    setattr(tts, "_synthesize_jobs", fake_voice)
    setattr(tts, "_check_voice", no_check)


def dub(work: Path):
    """pipeline.dub with the stock voice and no separation: the path that has to work on a Mac."""
    from opendub import pipeline
    from opendub.config import Settings

    return pipeline.dub(VID, Settings(work_root=work, tts="edge", separate=False))


if __name__ == "__main__":  # the macOS CI check: python tests/e2e_flow.py <empty dir>
    import sys
    import tempfile

    work = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
    make_video(work)
    install_fakes(setattr)
    out = dub(work)
    assert out.exists(), out
    leaked = [m for m in ("torch", "torchaudio", "demucs", "chatterbox") if m in sys.modules]
    assert not leaked, f"the edge path without separation imported {leaked}"
    print(f"ok: {out}")
