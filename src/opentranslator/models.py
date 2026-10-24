"""Estructuras de datos compartidas entre fases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Segment:
    id: int
    start: float  # segundos
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def save_segments(path: Path, segments: list[Segment]) -> None:
    path.write_text(
        json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_segments(path: Path) -> list[Segment]:
    return [Segment(**d) for d in json.loads(path.read_text(encoding="utf-8"))]
