"""Data structures shared between phases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .workdir import write_text_atomic


@dataclass
class Segment:
    id: int
    start: float  # seconds
    end: float
    text: str
    speaker: str | None = None  # A, B, C… with --multi-speaker (diarize.py); None: the one voice

    @property
    def duration(self) -> float:
        return self.end - self.start


def save_segments(path: Path, segments: list[Segment]) -> None:
    # without "speaker" when there is none, so single-voice files stay as they were
    rows = [{k: v for k, v in asdict(s).items() if k != "speaker" or v is not None} for s in segments]
    write_text_atomic(path, json.dumps(rows, ensure_ascii=False, indent=2))


def load_segments(path: Path) -> list[Segment]:
    return [Segment(**d) for d in json.loads(path.read_text(encoding="utf-8"))]
