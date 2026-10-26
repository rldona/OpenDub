"""Phase B: split the original audio into vocals and background (music and effects).

HTDemucs separates drums, bass, other and vocals; the background is everything
but the vocals. On Apple Silicon it runs on MLX (demucs-mlx); elsewhere on
PyTorch (demucs), on CUDA when a GPU is available. Both expose the same
`Separator.separate_tensor` API, so only the import and device differ.

The audio is never held whole: ffmpeg decodes it as a stream, the model separates
CHUNK_S at a time with OVERLAP_S shared with the next chunk (crossfaded, so no seam
is heard), and the stems are written to their wavs as they come. A 60 min video
needs about the memory of a few minutes, instead of ~3 GB for the audio and its
four stems.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from rich.progress import BarColumn, TimeElapsedColumn

from . import media
from .config import Settings
from .errors import PhaseError
from .log import Progress, console, log
from .workdir import WorkDir

MODEL = "htdemucs"
SAMPLE_RATE = 44100
CHUNK_S = 300.0  # seconds separated at a time
OVERLAP_S = 5.0  # shared with the next chunk and crossfaded: htdemucs sees the context on both sides

Separate = Callable[[np.ndarray], dict[str, np.ndarray]]
INSTALL_HINT = "Install the optional dependencies with: uv sync --extra separate"


def resolve_backend(choice: str) -> str:
    """auto → mlx on Apple Silicon, torch everywhere else."""
    if choice not in ("auto", "mlx", "torch"):
        raise SystemExit(f"--separator must be auto, mlx or torch (not {choice!r})")
    if choice != "auto":
        return choice
    return "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "torch"


def split_stems(stems: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(vocals, background), where background is the sum of every non-vocal stem."""
    if "vocals" not in stems:
        raise ValueError(f"The model returned no vocals stem (got {', '.join(stems)})")
    others = [audio for name, audio in stems.items() if name != "vocals"]
    if not others:
        raise ValueError("The model returned only the vocals stem")
    return stems["vocals"], np.sum(others, axis=0)


@contextmanager
def _separator(backend: str) -> Iterator[Separate]:
    """The model, loaded once: a function from a (2, samples) chunk to its stems."""
    if backend == "mlx":
        try:
            from demucs_mlx import Separator as MlxSeparator
        except ImportError:
            raise PhaseError("engine_missing", f"demucs-mlx is not installed. {INSTALL_HINT}",
                             engine="demucs-mlx", cmd="uv sync --extra separate")
        log.info(f"Separating with demucs-mlx ({MODEL}, Apple GPU)…")
        with MlxSeparator(model=MODEL, progress=False) as mlx:
            yield lambda audio: {name: np.asarray(s) for name, s in mlx.separate_tensor(audio)[1].items()}
        return
    try:
        import torch
        from demucs.api import Separator
    except ImportError:
        raise PhaseError("engine_missing", f"demucs (PyTorch) is not installed. {INSTALL_HINT}",
                         engine="demucs", cmd="uv sync --extra separate")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    log.info(f"Separating with demucs ({MODEL}, {name})…")
    separator = Separator(model=MODEL, device=device, progress=False)
    yield lambda audio: {n: s.cpu().numpy() for n, s in separator.separate_tensor(torch.from_numpy(audio))[1].items()}


@contextmanager
def _stream(path: Path) -> Iterator[subprocess.Popen]:
    """ffmpeg decoding `path` to float32 stereo at 44.1 kHz on its stdout."""
    proc = media.popen(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
                        "-f", "f32le", "-"], stdout=subprocess.PIPE)
    try:
        yield proc
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()


def _read(stdout, samples: int) -> np.ndarray:
    """Up to `samples` stereo samples from the stream, shaped (2, n); fewer only at its end."""
    want = samples * 2 * 4
    data = bytearray()
    while len(data) < want and (piece := stdout.read(want - len(data))):
        data += piece
    data = data[: len(data) - len(data) % 8]  # whole stereo frames
    return np.frombuffer(bytes(data), dtype=np.float32).reshape(-1, 2).T.copy()


class _Writer:
    """A 16-bit stereo wav written a piece at a time."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp = path.with_suffix(".part.wav")
        self.path = path
        self.w = wave.open(str(self.tmp), "wb")
        self.w.setnchannels(2)
        self.w.setsampwidth(2)
        self.w.setframerate(SAMPLE_RATE)

    def write(self, audio: np.ndarray) -> None:
        self.w.writeframes((np.clip(audio, -1.0, 1.0).T * 32767).astype(np.int16).tobytes())

    def close(self) -> None:
        self.w.close()
        self.tmp.replace(self.path)  # a separation cut short leaves no half stem behind


def separate_stream(stdout, separate: Separate, vocals: _Writer, background: _Writer,
                    chunk: int, overlap: int, done: Callable[[float], None] = lambda s: None) -> int:
    """Separate a decoded stream chunk by chunk into the two writers; returns the samples written.

    Each window is the previous one's last `overlap` samples plus up to `chunk` new ones
    (chunk >= overlap). Over those shared samples both windows' stems are crossfaded
    linearly; the rest of each window is written as the model gave it.
    """
    carry = np.zeros((2, 0), dtype=np.float32)  # the input shared with the next window
    tail = (carry, carry)  # the stems the previous window gave over it
    written = 0
    while True:
        new = _read(stdout, chunk)
        if new.shape[1] == 0:  # the stream ended with the previous window: its tail is the end
            vocals.write(tail[0])
            background.write(tail[1])
            return written + tail[0].shape[1]
        last = new.shape[1] < chunk
        window = np.concatenate([carry, new], axis=1)
        voc, bg = split_stems(separate(window))
        n = carry.shape[1]
        fade = np.linspace(0.0, 1.0, n, dtype=np.float32)
        vocals.write(tail[0] * (1 - fade) + voc[:, :n] * fade)
        background.write(tail[1] * (1 - fade) + bg[:, :n] * fade)
        end = window.shape[1] if last else window.shape[1] - overlap
        vocals.write(voc[:, n:end])
        background.write(bg[:, n:end])
        written += end
        done(written / SAMPLE_RATE)
        if last:
            return written
        tail, carry = (voc[:, end:], bg[:, end:]), window[:, end:]


def run(wd: WorkDir, settings: Settings, force: bool = False) -> tuple[Path, Path]:
    # The backend is not part of the cache key: both run the same model
    params = {"model": MODEL}
    if not force and wd.is_done("separate", params) and wd.vocals.exists() and wd.background.exists():
        log.info("Separation cached, skipping")
        return wd.vocals, wd.background

    backend = resolve_backend(settings.separator)
    total = media.duration(wd.video)
    start = time.monotonic()
    vocals, background = _Writer(wd.vocals), _Writer(wd.background)
    with _separator(backend) as separate, _stream(wd.video) as proc, Progress(
        "[progress.description]{task.description}", BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%", TimeElapsedColumn(),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("Separating", total=total)
        samples = separate_stream(proc.stdout, separate, vocals, background,
                                  int(CHUNK_S * SAMPLE_RATE), int(OVERLAP_S * SAMPLE_RATE),
                                  lambda s: progress.update(task, completed=s))
    vocals.close()
    background.close()
    duration = samples / SAMPLE_RATE
    elapsed = time.monotonic() - start
    log.info(f"Separated {duration:.0f}s of audio in {elapsed:.1f}s ({duration / elapsed:.1f}× real time)")
    wd.mark_done("separate", params)
    return wd.vocals, wd.background
