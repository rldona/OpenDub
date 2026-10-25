"""Exports of a kept dub: subtitles, an MKV with both audio tracks, the dubbed audio alone.

Made on demand from a version's own files (outputs/<version>.mp4 and .tts.json)
and kept next to them, so asking again is instant. Nothing is re-encoded.

- srt: what the dubbed voice says, timed where the mix placed each clip (after
  the delays that keep clips from overlapping), so it follows the voice heard.
- srt-orig: the original sentences, at the original timestamps.
- mkv: the video, the dubbed audio (default track), the original audio and both
  subtitles as selectable tracks.
- m4a: the dubbed audio track alone.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from .media import ffmpeg
from .mix import VERSION, place
from .models import load_segments
from .tts import Clip
from .workdir import WorkDir

FORMATS = {"srt": ".es.srt", "srt-orig": ".orig.srt", "mkv": ".mkv", "m4a": ".m4a"}
LINE_CHARS = 42  # subtitle line length that reads comfortably
# ISO 639-1 (YouTube's language) → ISO 639-2, which MKV track tags use
LANG_639_2 = {"en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita", "pt": "por", "ja": "jpn",
              "ko": "kor", "zh": "chi", "ru": "rus", "nl": "dut", "pl": "pol", "tr": "tur", "ar": "ara"}


def version_stem(wd: WorkDir, version: str | None = None) -> str:
    """The kept version's file stem in outputs/; None or "latest": the one output.mp4 is.
    LookupError if there is no such dub."""
    outputs = wd.outputs_dir
    if version in (None, "latest"):
        if wd.output.exists() and outputs.exists():
            for kept in sorted(outputs.glob("*.mp4")):
                if VERSION.fullmatch(kept.stem) and kept.samefile(wd.output):
                    return kept.stem
        raise LookupError("No dub yet")
    if not VERSION.fullmatch(version) or not (outputs / f"{version}.mp4").exists():
        raise LookupError(version)
    return version


def _clips(index_path: Path) -> list[Clip]:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return [Clip(**c) for c in (data["clips"] if isinstance(data, dict) else data)]


def _time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _split(start: float, end: float, text: str) -> list[tuple[float, float, list[str]]]:
    """A cue in screens of up to two lines, each shown for its share of the characters."""
    lines = textwrap.wrap(" ".join(text.split()), LINE_CHARS) or [text]
    screens = [lines[i : i + 2] for i in range(0, len(lines), 2)]
    total = sum(len(" ".join(sc)) for sc in screens)
    out, t = [], start
    for sc in screens:
        share = (end - start) * len(" ".join(sc)) / total
        out.append((t, t + share, sc))
        t += share
    return out


def _srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = []
    for start, end, text in cues:
        for a, b, lines in _split(start, end, text):
            blocks.append(f"{len(blocks) + 1}\n{_time(a)} --> {_time(b)}\n" + "\n".join(lines) + "\n")
    return "\n".join(blocks)


def dubbed_srt(clips: list[Clip]) -> str:
    """Subtitles of what the dubbed voice says, where the mix placed each clip."""
    by_id = {c.id: c for c in clips}
    cues = [(p.start, p.start + by_id[p.id].duration, by_id[p.id].text) for p in place(clips)]
    return _srt([cue for cue in cues if cue[2].strip()])


def original_srt(wd: WorkDir) -> str:
    return _srt([(s.start, s.end, s.text) for s in load_segments(wd.segments) if s.text.strip()])


def export(wd: WorkDir, fmt: str, version: str | None = None) -> Path:
    """The file of a version in that format, made now if it isn't kept already."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)} (not {fmt!r})")
    stem = version_stem(wd, version)
    video = wd.outputs_dir / f"{stem}.mp4"
    out = wd.outputs_dir / f"{stem}{FORMATS[fmt]}"
    if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
        return out
    tmp = out.with_name(f"{out.stem}.part{out.suffix}")
    if fmt in ("srt", "srt-orig"):
        index = wd.outputs_dir / f"{stem}.tts.json"
        if fmt == "srt" and not index.exists():
            raise LookupError(f"{stem} has no tts.json to time its subtitles")
        tmp.write_text(dubbed_srt(_clips(index)) if fmt == "srt" else original_srt(wd), encoding="utf-8")
    elif fmt == "m4a":
        ffmpeg("-i", str(video), "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", str(tmp))
    else:
        if not wd.video.exists():
            raise ValueError("The original video was deleted to save space: dub or retouch the video to download "
                             "it again, then export the MKV with its original audio")
        es, orig = export(wd, "srt", stem), export(wd, "srt-orig", stem)
        meta = json.loads(wd.meta.read_text(encoding="utf-8")) if wd.meta.exists() else {}
        lang = LANG_639_2.get((meta.get("language") or "").split("-")[0], "und")
        ffmpeg(
            "-i", str(video), "-i", str(wd.video), "-i", str(es), "-i", str(orig),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:a:0", "-map", "2:0", "-map", "3:0",
            "-c", "copy", "-c:s", "srt",
            "-metadata:s:a:0", "language=spa", "-metadata:s:a:0", "title=Español (doblaje)",
            "-metadata:s:a:1", f"language={lang}", "-metadata:s:a:1", "title=Original",
            "-metadata:s:s:0", "language=spa", "-metadata:s:s:0", "title=Español",
            "-metadata:s:s:1", f"language={lang}", "-metadata:s:s:1", "title=Original",
            "-disposition:a:0", "default", "-disposition:a:1", "0",
            "-disposition:s:0", "0", "-disposition:s:1", "0",
            str(tmp),
        )
    tmp.replace(out)
    return out
