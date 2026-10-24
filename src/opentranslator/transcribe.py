"""Phase 2: timestamped transcription (YouTube subtitles or faster-whisper)."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
from rich.progress import BarColumn, Progress, TimeElapsedColumn

from .config import Settings
from .log import console, log
from .models import Segment, load_segments, save_segments
from .segments import Piece, parse_subtitles, regroup
from .workdir import WorkDir


def _choose_source(meta: dict[str, Any], subs_mode: str) -> str:
    """Priority: manual → (auto-generated if --subs auto) → whisper."""
    if subs_mode not in ("manual", "auto", "none"):
        raise SystemExit(f"--subs debe ser manual, auto o none (no {subs_mode!r})")
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


def _whisper(wd: WorkDir, model_name: str, lang: str | None) -> tuple[list[Piece], str]:
    from faster_whisper import WhisperModel  # lazy import: slow to load

    log.info(f"Cargando modelo whisper [bold]{model_name}[/] (CPU int8)…")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        _load_wav(wd.audio),
        language=lang.split("-")[0] if lang else None,
        word_timestamps=True,
        vad_filter=True,
    )
    if not lang:
        log.info(f"Idioma detectado: {info.language} ({info.language_probability:.0%})")

    pieces: list[Piece] = []
    with Progress(
        "[progress.description]{task.description}", BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%", TimeElapsedColumn(),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("Transcribiendo", total=info.duration)
        for seg in segments:
            pieces.extend(Piece(w.start, w.end, w.word) for w in seg.words or [])
            progress.update(task, completed=seg.end)
    return pieces, info.language


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Segment]:
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    source = _choose_source(meta, settings.subs)
    params = {"source": source, "whisper_model": settings.whisper_model if source == "whisper" else None}
    if not force and wd.is_done("transcribe", params) and wd.segments.exists():
        log.info("Transcripción en caché, la salto")
        return load_segments(wd.segments)

    if source == "whisper":
        pieces, detected = _whisper(wd, settings.whisper_model, meta.get("language"))
        if not meta.get("language"):
            meta["language"] = detected
            wd.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path = wd.path / meta["subs"][source]
        log.info(f"Usando subtítulos {source}: {path.name}")
        pieces = parse_subtitles(path)

    segments = regroup(pieces)
    if not segments:
        raise SystemExit("No se ha obtenido ningún segmento de texto")
    save_segments(wd.segments, segments)
    durs = [s.duration for s in segments]
    log.info(
        f"{len(pieces)} piezas → {len(segments)} segmentos · "
        f"duración media {sum(durs) / len(durs):.1f}s, máx {max(durs):.1f}s"
    )
    wd.mark_done("transcribe", params)
    return segments
