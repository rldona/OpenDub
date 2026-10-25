"""Corrections to who speaks, made from the web page (several voices).

The diarization can give a sentence to the wrong person or split one person in
two. speakers.json keeps what was corrected by hand, so a translation made
again (translate.run) keeps it, like the text edits:

    {"names": {"A": "Andy"}, "segments": {"17": "B"}}

- names: what to call each speaker on the page;
- segments: sentences given to another speaker. Merging B into A gives every
  sentence of B to A.

A correction goes into translation.json at once; the TTS phase then sees the
sentence as pending (tts.pending_edits) and a retouch speaks it with the right
voice. The sentence keeps the translation made for the speaker it had.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .models import Segment, load_segments, save_segments
from .workdir import WorkDir

FILE = "speakers.json"


def load(wd: WorkDir) -> dict[str, Any]:
    path = wd.path / FILE
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"names": data.get("names") or {}, "segments": data.get("segments") or {}}


def _save(wd: WorkDir, data: dict[str, Any]) -> None:
    (wd.path / FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def apply(wd: WorkDir, segments: list[Segment]) -> list[Segment]:
    """The segments with the speakers corrected by hand."""
    fixed = load(wd)["segments"]
    if not fixed:
        return segments
    return [replace(s, speaker=fixed.get(str(s.id), s.speaker)) for s in segments]


def known(wd: WorkDir) -> list[str]:
    """The diarization's speakers (A, B, C…)."""
    if not wd.diarization.exists():
        return []
    return list(json.loads(wd.diarization.read_text(encoding="utf-8"))["speakers"])


def reassign(wd: WorkDir, changes: dict[int, str]) -> None:
    """Give sentences to other speakers. KeyError: no such sentence; ValueError: no such speaker."""
    speakers = set(known(wd))
    bad = sorted(set(changes.values()) - speakers)
    if bad:
        raise ValueError(f"No speaker {bad[0]}")
    segments = load_segments(wd.translation)
    ids = {s.id for s in segments}
    missing = sorted(set(changes) - ids)
    if missing:
        raise KeyError(missing[0])
    data = load(wd)
    data["segments"].update({str(i): spk for i, spk in changes.items()})
    _save(wd, data)
    save_segments(wd.translation, [replace(s, speaker=changes.get(s.id, s.speaker)) for s in segments])
    wd.invalidate_from("tts")  # like a text edit: TTS and mix are behind until a retouch or a dub


def merge(wd: WorkDir, source: str, target: str) -> int:
    """Give every sentence of `source` to `target` (one person split in two); how many moved."""
    if source == target:
        raise ValueError("A speaker can't be merged into itself")
    moved = {s.id: target for s in load_segments(wd.translation) if s.speaker == source}
    if moved:
        reassign(wd, moved)
    return len(moved)


def rename(wd: WorkDir, speaker: str, name: str) -> None:
    if speaker not in known(wd):
        raise ValueError(f"No speaker {speaker}")
    data = load(wd)
    if name.strip():
        data["names"][speaker] = name.strip()
    else:
        data["names"].pop(speaker, None)
    _save(wd, data)
