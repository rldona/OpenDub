"""Shared by the diarization runners, which each run in their own venv (stdlib + numpy only here)."""

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SR = 16000


def load(path: Path) -> np.ndarray:
    """Mono float32 at 16 kHz, decoded by ffmpeg."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def write(out: Path, model: str, turns: list[tuple[float, float, str]], started: float, load_s: float) -> None:
    import torch

    vram = torch.cuda.max_memory_allocated() / 2**30 if torch.cuda.is_available() else None
    data = {"model": model, "seconds": round(time.monotonic() - started, 1), "load_s": round(load_s, 1),
            "vram_gb": round(vram, 2) if vram else None,
            "turns": [[round(a, 3), round(b, 3), str(s)] for a, b, s in sorted(turns)]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    speakers = sorted({t[2] for t in data["turns"]})
    print(f"{model}: {len(data['turns'])} turns, {len(speakers)} speakers, {data['seconds']}s "
          f"(load {data['load_s']}s), VRAM {data['vram_gb']} GB → {out}", file=sys.stderr)
