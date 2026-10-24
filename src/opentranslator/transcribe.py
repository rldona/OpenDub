"""Phase 2: timestamped transcription (YouTube subtitles or faster-whisper)."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
from rich.progress import BarColumn, TimeElapsedColumn

from .config import Settings
from .log import Progress, console, log
from .models import Segment, load_segments, save_segments
from .segments import Piece, parse_subtitles, regroup
from .workdir import WorkDir


def _choose_source(meta: dict[str, Any], subs_mode: str) -> str:
    """Priority: manual → (auto-generated if --subs auto) → whisper."""
    if subs_mode not in ("manual", "auto", "none"):
        raise SystemExit(f"--subs must be manual, auto or none (not {subs_mode!r})")
    subs = meta.get("subs", {})
    if subs_mode in ("manual", "auto") and subs.get("manual"):
        return "manual"
    if subs_mode == "auto" and subs.get("auto"):
        return "auto"
    return "whisper"


def _load_wav(path: Path) -> np.ndarray:
    """Read the 16 kHz mono wav (avoids faster-whisper's PyAV decoder)."""
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


# CUDA libraries CTranslate2 opens at runtime (cuBLAS for CUDA 12, cuDNN 9)
CUDA_LIBS = {"cublas": ["libcublasLt.so.12", "libcublas.so.12"], "cudnn": ["libcudnn*.so.9"]}


def _load_cuda_libs() -> bool:
    """Make cuBLAS and cuDNN loadable for CTranslate2; False if they can't be found.

    CTranslate2 looks them up in the system library path, but they usually come
    as pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12, pulled in by torch with
    the `separate` extra) that live inside the venv. Loading them globally by
    absolute path first lets CTranslate2's later dlopen find them by soname.
    """
    import ctypes
    import importlib.util

    for package, patterns in CUDA_LIBS.items():
        try:
            ctypes.CDLL(patterns[-1].replace("*", ""), mode=ctypes.RTLD_GLOBAL)
            continue  # already on the system library path
        except OSError:
            pass
        spec = importlib.util.find_spec(f"nvidia.{package}")
        if spec is None or not spec.submodule_search_locations:
            return False
        lib_dir = Path(next(iter(spec.submodule_search_locations))) / "lib"
        try:
            for pattern in patterns:
                for lib in sorted(lib_dir.glob(pattern)):
                    ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
        except OSError:
            return False
    return True


def whisper_device() -> tuple[str, str]:
    """(device, compute_type): CUDA in float16 when an NVIDIA GPU is usable, else CPU in int8.

    CTranslate2 has no Metal backend, so Apple Silicon always runs on the CPU.
    """
    import ctranslate2

    if ctranslate2.get_cuda_device_count() > 0:
        if _load_cuda_libs():
            return "cuda", "float16"
        log.warning(
            "NVIDIA GPU found but cuBLAS/cuDNN are missing, transcribing on the CPU. "
            "Install them with: uv sync --extra separate"
        )
    return "cpu", "int8"


def _whisper(wd: WorkDir, model_name: str, lang: str | None) -> tuple[list[Piece], str]:
    from faster_whisper import WhisperModel  # lazy import: slow to load

    device, compute_type = whisper_device()
    log.info(f"Loading whisper model [bold]{model_name}[/] ({device} {compute_type})…")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        _load_wav(wd.audio),
        language=lang.split("-")[0] if lang else None,
        word_timestamps=True,
        vad_filter=True,
    )
    if not lang:
        log.info(f"Detected language: {info.language} ({info.language_probability:.0%})")

    pieces: list[Piece] = []
    with Progress(
        "[progress.description]{task.description}", BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%", TimeElapsedColumn(),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("Transcribing", total=info.duration)
        for seg in segments:
            pieces.extend(Piece(w.start, w.end, w.word) for w in seg.words or [])
            progress.update(task, completed=seg.end)
    return pieces, info.language


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Segment]:
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    source = _choose_source(meta, settings.subs)
    params = {"source": source, "whisper_model": settings.whisper_model if source == "whisper" else None}
    if not force and wd.is_done("transcribe", params) and wd.segments.exists():
        log.info("Transcription cached, skipping")
        return load_segments(wd.segments)

    if source == "whisper":
        pieces, detected = _whisper(wd, settings.whisper_model, meta.get("language"))
        if not meta.get("language"):
            meta["language"] = detected
            wd.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path = wd.path / meta["subs"][source]
        log.info(f"Using {source} subtitles: {path.name}")
        pieces = parse_subtitles(path)

    segments = regroup(pieces)
    if not segments:
        raise SystemExit("No text segments were obtained")
    save_segments(wd.segments, segments)
    durs = [s.duration for s in segments]
    log.info(
        f"{len(pieces)} pieces → {len(segments)} segments · "
        f"mean duration {sum(durs) / len(durs):.1f}s, max {max(durs):.1f}s"
    )
    wd.mark_done("transcribe", params)
    return segments
