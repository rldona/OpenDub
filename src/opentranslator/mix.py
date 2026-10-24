"""Fase 5: composición de la pista doblada y mux con el vídeo original.

La pista doblada se compone en numpy (un clip por segmento en su timestamp) en
lugar de con cientos de entradas `adelay` en ffmpeg. Si un clip no cabe en su
hueco, el siguiente se empuja hacia delante en vez de solaparse; el desfase se
recupera solo en el siguiente silencio. Después, una única llamada a ffmpeg baja
el volumen del audio original, mezcla y copia el vídeo sin recodificar.
"""

from __future__ import annotations

import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .log import log
from .media import duration as media_duration
from .media import ffmpeg
from .tts import SAMPLE_RATE, Clip, load_clips
from .workdir import WorkDir

MIN_GAP = 0.08  # silencio mínimo entre dos clips empujados (s)


@dataclass
class Placement:
    id: int
    start: float  # posición real en la pista doblada
    delay: float  # retraso respecto al timestamp original


def place(clips: list[Clip], min_gap: float = MIN_GAP) -> list[Placement]:
    """Coloca cada clip en su timestamp o, si el anterior aún suena, justo detrás."""
    placements = []
    cursor = 0.0
    for c in sorted(clips, key=lambda c: c.start):
        start = c.start if c.start >= cursor else cursor + min_gap
        placements.append(Placement(c.id, round(start, 3), round(start - c.start, 3)))
        cursor = start + c.duration
    return placements


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
            raise ValueError(f"{path.name}: se esperaba wav mono a {SAMPLE_RATE} Hz")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def compose(clips: list[Clip], placements: list[Placement], base: Path, total: float) -> tuple[np.ndarray, int]:
    """Devuelve la pista doblada y cuántos clips se han tenido que recortar al final."""
    track = np.zeros(int(total * SAMPLE_RATE), dtype=np.float32)
    by_id = {c.id: c for c in clips}
    cut = 0
    for p in placements:
        audio = _read_wav(base / by_id[p.id].file)
        i = int(round(p.start * SAMPLE_RATE))
        if i >= len(track):
            cut += 1
            continue
        n = min(len(audio), len(track) - i)
        cut += n < len(audio)
        track[i : i + n] += audio[:n]
    return np.clip(track, -1.0, 1.0), cut


def _write_wav(path: Path, track: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((track * 32767).astype(np.int16).tobytes())


def run(wd: WorkDir, settings: Settings, force: bool = False, output: Path | None = None) -> Path:
    params = {"bg_volume_db": settings.bg_volume_db, "mute": settings.mute_original}
    if not force and wd.is_done("mix", params) and wd.output.exists():
        log.info("Mezcla en caché, la salto")
    else:
        clips = load_clips(wd)
        total = media_duration(wd.video)
        placements = place(clips)
        delayed = [p for p in placements if p.delay > 0]
        if delayed:
            log.info(
                f"Clips retrasados para no solaparse: {len(delayed)} "
                f"(máx {max(p.delay for p in delayed):.2f}s)"
            )
            with wd.overflow_log.open("a", encoding="utf-8") as f:
                for p in delayed:
                    f.write(f"#{p.id} retrasado {p.delay:.2f}s en la mezcla\n")

        track, cut = compose(clips, placements, wd.path, total)
        if cut:
            log.warning(f"{cut} clip(s) recortados por pasarse del final del vídeo")
        _write_wav(wd.dub, track)

        if settings.mute_original:
            log.info("Audio original silenciado")
            graph = "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0[a]"
        else:
            log.info(f"Audio original a {settings.bg_volume_db:+.0f} dB")
            graph = (
                f"[0:a]volume={settings.bg_volume_db}dB[bg];"
                "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0[dub];"
                "[bg][dub]amix=inputs=2:duration=first:normalize=0[a]"
            )
        log.info("Mezclando y muxeando (vídeo sin recodificar)…")
        ffmpeg(
            "-i", str(wd.video), "-i", str(wd.dub),
            "-filter_complex", graph,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", "-movflags", "+faststart",
            str(wd.output),
        )
        wd.mark_done("mix", params)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wd.output, output)
        log.info(f"Copiado a {output}")
        return output
    log.info(f"Resultado: [bold]{wd.output}[/]")
    return wd.output
