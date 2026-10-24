"""Phase B: split the original audio into vocals and background (music and effects).

HTDemucs separates drums, bass, other and vocals; the background is everything
but the vocals. On Apple Silicon it runs on MLX (demucs-mlx); elsewhere on
PyTorch (demucs), on CUDA when a GPU is available. Both expose the same
`Separator.separate_tensor` API, so only the import and device differ.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

from .config import Settings
from .log import log
from .workdir import WorkDir

MODEL = "htdemucs"
SAMPLE_RATE = 44100
INSTALL_HINT = "Install the optional dependencies with: uv sync --extra separate"


def resolve_backend(choice: str) -> str:
    """auto → mlx on Apple Silicon, torch everywhere else."""
    if choice not in ("auto", "mlx", "torch"):
        raise SystemExit(f"--separator must be auto, mlx or torch (not {choice!r})")
    if choice != "auto":
        return choice
    return "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "torch"


def _load(path: Path) -> np.ndarray:
    """Decode any audio/video file to float32 stereo at 44.1 kHz, shaped (2, samples)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()


def _save(path: Path, audio: np.ndarray) -> None:
    """Write a (channels, samples) float array as 16-bit wav."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0).T * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(audio.shape[0])
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def split_stems(stems: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(vocals, background), where background is the sum of every non-vocal stem."""
    if "vocals" not in stems:
        raise ValueError(f"The model returned no vocals stem (got {', '.join(stems)})")
    background = sum(audio for name, audio in stems.items() if name != "vocals")
    return stems["vocals"], background


def _separate_mlx(audio: np.ndarray) -> dict[str, np.ndarray]:
    try:
        from demucs_mlx import Separator
    except ImportError:
        raise SystemExit(f"demucs-mlx is not installed. {INSTALL_HINT}")
    log.info(f"Separating with demucs-mlx ({MODEL}, Apple GPU)…")
    with Separator(model=MODEL, progress=True) as separator:
        _, stems = separator.separate_tensor(audio)
    return {name: np.asarray(s) for name, s in stems.items()}


def _separate_torch(audio: np.ndarray) -> dict[str, np.ndarray]:
    try:
        import torch
        from demucs.api import Separator
    except ImportError:
        raise SystemExit(f"demucs (PyTorch) is not installed. {INSTALL_HINT}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    log.info(f"Separating with demucs ({MODEL}, {name})…")
    separator = Separator(model=MODEL, device=device, progress=True)
    _, stems = separator.separate_tensor(torch.from_numpy(audio))
    return {name: s.cpu().numpy() for name, s in stems.items()}


def run(wd: WorkDir, settings: Settings, force: bool = False) -> tuple[Path, Path]:
    # The backend is not part of the cache key: both run the same model
    params = {"model": MODEL}
    if not force and wd.is_done("separate", params) and wd.vocals.exists() and wd.background.exists():
        log.info("Separation cached, skipping")
        return wd.vocals, wd.background

    backend = resolve_backend(settings.separator)
    audio = _load(wd.video)
    duration = audio.shape[1] / SAMPLE_RATE
    start = time.monotonic()
    stems = _separate_mlx(audio) if backend == "mlx" else _separate_torch(audio)
    elapsed = time.monotonic() - start
    vocals, background = split_stems(stems)
    _save(wd.vocals, vocals)
    _save(wd.background, background)
    log.info(f"Separated {duration:.0f}s of audio in {elapsed:.1f}s ({duration / elapsed:.1f}× real time)")
    wd.mark_done("separate", params)
    return wd.vocals, wd.background
