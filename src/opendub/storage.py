"""What a video takes on disk, and deleting what can be made again (the web page's Storage card).

Kept for good: the versions (outputs/*.mp4 with their tts.json and overflow.log),
the transcription and translation, the dub's tts.json, its references and settings.
Deletable per video, each group saying what is lost and what is redone (no automatic
deletion):

- source: video.mp4 and audio.wav. Downloaded again (needs YouTube) when a dub or a
  retouch needs them; until then the MKV with the original audio can't be exported.
- stems: the separated vocals and background. Separated again before the next dub
  or retouch with a cloned voice or the music kept.
- raw: the raw clips each engine spoke (a cache keyed by text, voice and seed).
  Nothing is lost: whatever is spoken again is synthesized again.
- clips: the latest dub's processed voice clips. Retouching and remixing need them,
  so the next dub speaks the voice again (from the raw cache if it is still there).
- exports: MKV, M4A and SRT made from the versions; made again on request.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .export import FORMATS
from .workdir import WorkDir

GROUPS = ("source", "stems", "raw", "clips", "exports")


def _files(wd: WorkDir, group: str) -> list[Path]:
    if group == "source":
        return [p for p in (wd.video, wd.audio) if p.exists()]
    if group == "stems":
        return sorted(wd.vocals.parent.glob("*")) if wd.vocals.parent.exists() else []
    if group == "raw":
        raw = wd.tts_dir / "raw"
        return sorted(raw.iterdir()) if raw.exists() else []
    if group == "clips":
        return sorted(wd.tts_dir.glob("*.wav")) if wd.tts_dir.exists() else []
    if group == "exports":
        if not wd.outputs_dir.exists():
            return []
        return sorted(p for p in wd.outputs_dir.iterdir() if any(p.name.endswith(s) for s in FORMATS.values()))
    raise KeyError(group)


def _size(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.is_file())


def usage(wd: WorkDir) -> dict:
    """{"groups": [{"id", "bytes", "files"}], "kept": bytes that always stay}."""
    groups = []
    deletable: set[Path] = set()
    for group in GROUPS:
        files = _files(wd, group)
        deletable.update(files)
        groups.append({"id": group, "bytes": _size(files), "files": len(files)})
    everything = [p for p in wd.path.rglob("*") if p.is_file() and p.name != ".lock"]
    kept = _size([p for p in everything if p not in deletable])
    return {"groups": groups, "kept": kept}


def delete(wd: WorkDir, group: str) -> int:
    """Delete a group's files; how many bytes it freed. KeyError: no such group."""
    files = _files(wd, group)
    freed = _size(files)
    for path in files:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return freed
