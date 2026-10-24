"""Per-video working folder and phase cache.

Each phase records in manifest.json a hash of the parameters that affect it. A
phase counts as done if its hash matches; redoing a phase invalidates every
phase after it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

STEPS = ["download", "transcribe", "translate", "tts", "mix"]


def params_hash(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class WorkDir:
    def __init__(self, root: Path, video_id: str):
        self.path = root / video_id
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.path / "manifest.json"

    # Paths of each phase's artifacts
    meta = property(lambda self: self.path / "meta.json")
    video = property(lambda self: self.path / "video.mp4")
    audio = property(lambda self: self.path / "audio.wav")
    segments = property(lambda self: self.path / "segments.json")
    translation = property(lambda self: self.path / "translation.json")
    tts_dir = property(lambda self: self.path / "tts")
    tts_index = property(lambda self: self.path / "tts.json")
    dub = property(lambda self: self.path / "dub.wav")
    overflow_log = property(lambda self: self.path / "overflow.log")
    output = property(lambda self: self.path / "output.mp4")

    def _read(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.manifest_path.write_text(json.dumps(data, indent=2))

    def is_done(self, step: str, params: dict[str, Any]) -> bool:
        entry = self._read().get(step)
        return bool(entry) and entry["hash"] == params_hash(params)

    def has(self, step: str) -> bool:
        return step in self._read()

    def mark_done(self, step: str, params: dict[str, Any]) -> None:
        data = self._read()
        for later in STEPS[STEPS.index(step) + 1 :]:
            data.pop(later, None)
        data[step] = {"hash": params_hash(params), "at": datetime.now().isoformat()}
        self._write(data)

    def invalidate_from(self, step: str) -> None:
        data = self._read()
        for s in STEPS[STEPS.index(step) :]:
            data.pop(s, None)
        self._write(data)
