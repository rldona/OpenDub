"""Fase 4: TTS por segmento con edge-tts y ajuste de velocidad con atempo.

Por cada segmento traducido:
1. Sintetiza el mp3 con edge-tts (cacheado por voz+texto, así que retocar una
   frase solo regenera esa).
2. Recorta el silencio inicial y final y lo pasa a wav mono de 24 kHz.
3. Si no cabe en su hueco (hasta el inicio del siguiente segmento), acelera con
   atempo hasta max_tempo. Lo que siga sin caber se registra en overflow.log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TimeElapsedColumn

from .config import Settings
from .log import console, log
from .media import ffmpeg
from .models import Segment, load_segments
from .workdir import WorkDir

SAMPLE_RATE = 24000
CONCURRENCY = 4
MAX_ATTEMPTS = 3
TRIM = (
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse"
)


@dataclass
class Clip:
    id: int
    start: float
    slot: float  # segundos disponibles hasta el siguiente segmento
    raw_duration: float  # duración tras recortar silencios, antes de atempo
    tempo: float
    duration: float  # duración final
    overflow: float  # segundos que siguen sin caber (0 si cabe)
    file: str


def choose_tempo(duration: float, slot: float, seg_duration: float, min_tempo: float, max_tempo: float) -> float:
    """Factor de atempo: acelera si no cabe; ralentiza solo si min_tempo < 1."""
    if duration > slot:
        return min(duration / slot, max_tempo)
    if min_tempo < 1.0 and duration < seg_duration:
        return max(duration / seg_duration, min_tempo)
    return 1.0


def _slots(segments: list[Segment], media_duration: float | None) -> list[float]:
    slots = []
    for i, seg in enumerate(segments):
        end = segments[i + 1].start if i + 1 < len(segments) else (media_duration or seg.end + 2.0)
        slots.append(max(end - seg.start, 0.1))
    return slots


def _wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def check_rate(rate: str) -> str:
    """Valida el formato de velocidad de edge-tts: "+0%", "-10%"…"""
    if not re.fullmatch(r"[+-]\d{1,2}%", rate):
        raise SystemExit(f"--rate debe tener la forma -10% o +5% (no {rate!r})")
    return rate


def _raw_path(wd: WorkDir, voice: str, rate: str, text: str) -> Path:
    key = hashlib.sha256(f"{voice}\n{rate}\n{text}".encode()).hexdigest()[:16]
    return wd.tts_dir / "raw" / f"{key}.mp3"


async def _synthesize_all(jobs: list[tuple[str, Path]], voice: str, rate: str) -> None:
    import edge_tts

    sem = asyncio.Semaphore(CONCURRENCY)
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Sintetizando voz", total=len(jobs))

        async def one(text: str, path: Path) -> None:
            async with sem:
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    try:
                        tmp = path.with_suffix(".part")
                        await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
                        tmp.rename(path)
                        break
                    except Exception as e:  # edge-tts no tipa bien sus errores de red
                        if attempt == MAX_ATTEMPTS:
                            raise RuntimeError(f"edge-tts falló con {text[:40]!r}: {e}") from e
                        await asyncio.sleep(2 * attempt)
            progress.advance(task)

        await asyncio.gather(*(one(t, p) for t, p in jobs))


async def _check_voice(voice: str) -> None:
    import edge_tts

    voices = {v["ShortName"] for v in await edge_tts.list_voices()}
    if voice not in voices:
        spanish = ", ".join(sorted(v for v in voices if v.startswith("es-")))
        raise SystemExit(f"La voz {voice!r} no existe. Voces en español: {spanish}")


def _process(seg: Segment, slot: float, raw: Path, out_dir: Path, settings: Settings) -> Clip:
    trimmed = out_dir / f"{seg.id:04d}.trim.wav"
    final = out_dir / f"{seg.id:04d}.wav"
    ffmpeg("-i", str(raw), "-af", TRIM, "-ac", "1", "-ar", str(SAMPLE_RATE), str(trimmed))
    raw_dur = _wav_duration(trimmed)
    tempo = choose_tempo(raw_dur, slot, seg.duration, settings.min_tempo, settings.max_tempo)
    if abs(tempo - 1.0) > 0.01:
        ffmpeg("-i", str(trimmed), "-af", f"atempo={tempo:.4f}", str(final))
        trimmed.unlink()
    else:
        tempo = 1.0
        trimmed.replace(final)
    duration = _wav_duration(final)
    return Clip(
        id=seg.id, start=seg.start, slot=round(slot, 3), raw_duration=round(raw_dur, 3),
        tempo=round(tempo, 3), duration=round(duration, 3),
        overflow=round(max(duration - slot, 0.0), 3), file=f"tts/{final.name}",
    )


def load_clips(wd: WorkDir) -> list[Clip]:
    return [Clip(**c) for c in json.loads(wd.tts_index.read_text(encoding="utf-8"))]


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Clip]:
    segments = load_segments(wd.translation)
    params = {
        "voice": settings.voice,
        "rate": check_rate(settings.rate),
        "min_tempo": settings.min_tempo,
        "max_tempo": settings.max_tempo,
        "texts": [(s.id, s.start, s.text) for s in segments],
    }
    if not force and wd.is_done("tts", params) and wd.tts_index.exists():
        log.info("TTS en caché, lo salto")
        return load_clips(wd)

    asyncio.run(_check_voice(settings.voice))
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    for old in wd.tts_dir.glob("*.wav"):
        old.unlink()

    raws = [_raw_path(wd, settings.voice, settings.rate, s.text) for s in segments]
    if force:
        for p in raws:
            p.unlink(missing_ok=True)
    pending = {p: s.text for s, p in zip(segments, raws) if not p.exists()}
    log.info(f"Voz {settings.voice} ({settings.rate}) · {len(segments)} segmentos, {len(pending)} por sintetizar")
    if pending:
        asyncio.run(_synthesize_all([(t, p) for p, t in pending.items()], settings.voice, settings.rate))

    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = _slots(segments, meta.get("duration"))
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        clips = list(pool.map(
            lambda args: _process(*args, wd.tts_dir, settings), zip(segments, slots, raws)
        ))

    wd.tts_index.write_text(json.dumps([asdict(c) for c in clips], indent=1), encoding="utf-8")
    overflows = [c for c in clips if c.overflow > 0]
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        for c, s in zip(clips, segments):
            if c.overflow > 0:
                f.write(
                    f"#{c.id} @{c.start:.2f}s: dura {c.duration:.2f}s a {c.tempo}x, hueco {c.slot:.2f}s "
                    f"(+{c.overflow:.2f}s) · {s.text}\n"
                )

    sped = sum(1 for c in clips if c.tempo > 1.0)
    chars_per_s = sum(len(s.text) for s in segments) / sum(c.raw_duration for c in clips)
    log.info(
        f"Acelerados: {sped} · no caben: {len(overflows)}"
        + (f" (máx +{max(c.overflow for c in overflows):.2f}s, ver overflow.log)" if overflows else "")
    )
    log.info(f"Velocidad de locución medida: {chars_per_s:.1f} caracteres/s")
    wd.mark_done("tts", params)
    return clips
