"""Per-video working folder and phase cache.

Each phase records in manifest.json a hash of the parameters that affect it. A
phase counts as done if its hash matches; redoing a phase invalidates every
phase that depends on it, directly or indirectly.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

# Each phase and the phases whose output it reads
DEPENDS: dict[str, list[str]] = {
    "download": [],
    "transcribe": ["download"],
    "translate": ["transcribe"],
    "tts": ["translate"],
    "separate": ["download"],
    "diarize": ["separate"],  # transcribe reads it with --multi-speaker (its params record which)
    "mix": ["tts", "separate"],
}


def write_text_atomic(path: Path, text: str) -> None:
    """Write a file so that nobody ever reads it half written: a process killed while saving
    leaves the previous version. A temporary file next to it, then os.replace."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def dependents(step: str) -> set[str]:
    """Every phase that depends on `step`, directly or indirectly."""
    out: set[str] = set()
    frontier = [step]
    while frontier:
        current = frontier.pop()
        for s, deps in DEPENDS.items():
            if current in deps and s not in out:
                out.add(s)
                frontier.append(s)
    return out


def params_hash(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class WorkDir:
    def __init__(self, root: Path, video_id: str, create: bool = True):
        self.path = root / video_id
        if create:
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
    diarization = property(lambda self: self.path / "diarization.json")  # who speaks when (--multi-speaker)
    vocals = property(lambda self: self.path / "stems" / "vocals.wav")
    background = property(lambda self: self.path / "stems" / "background.wav")
    dub = property(lambda self: self.path / "dub.wav")
    overflow_log = property(lambda self: self.path / "overflow.log")
    output = property(lambda self: self.path / "output.mp4")
    thumbnail = property(lambda self: self.path / "thumbnail.jpg")
    outputs_dir = property(lambda self: self.path / "outputs")  # one dubbed video per engine
    translation_style = property(lambda self: self.path / "translation.style.json")  # style it was made with
    translation_edits = property(lambda self: self.path / "translation_edits.json")  # hand edits from the web
    job = property(lambda self: self.path / "job.json")  # web frontend: last job's options and outcome

    lock_path = property(lambda self: self.path / ".lock")

    @contextmanager
    def lock(self, what: str):
        """Hold this video for one process (a dub, a retouch, a phase): another one, from the CLI or
        the web, stops at once instead of writing the same files. The lock goes with the process."""
        import fcntl

        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise SystemExit(f"Another OpenDub process is working on this video ({self.holder() or 'unknown'}): "
                             "wait until it ends.") from None
        os.ftruncate(fd, 0)
        os.write(fd, f"pid {os.getpid()}, {what}".encode())
        try:
            yield
        finally:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def holder(self) -> str | None:
        """Who holds the lock ("pid 123, dub"), or None if nobody does."""
        import fcntl

        if not self.lock_path.exists():
            return None
        fd = os.open(self.lock_path, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return self.lock_path.read_text(encoding="utf-8").strip() or "another process"
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return None
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any]:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def _write(self, data: dict[str, Any]) -> None:
        write_text_atomic(self.manifest_path, json.dumps(data, indent=2))

    def is_done(self, step: str, params: dict[str, Any]) -> bool:
        entry = self._read().get(step)
        return bool(entry) and entry["hash"] == params_hash(params)

    def has(self, step: str) -> bool:
        return step in self._read()

    def mark_done(self, step: str, params: dict[str, Any]) -> None:
        data = self._read()
        for later in dependents(step):
            data.pop(later, None)
        data[step] = {"hash": params_hash(params), "at": datetime.now().isoformat()}
        self._write(data)

    def invalidate_from(self, step: str) -> None:
        data = self._read()
        for s in {step} | dependents(step):
            data.pop(s, None)
        self._write(data)
