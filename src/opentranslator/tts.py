"""Fase 4: TTS por segmento con edge-tts y ajuste de velocidad con atempo.

Por cada segmento traducido:
1. Sintetiza el mp3 con edge-tts (cacheado por voz+velocidad+texto, así que
   retocar una frase solo regenera esa).
2. Recorta el silencio inicial y final y lo pasa a wav mono de 24 kHz.
3. Si no cabe en su hueco (hasta el inicio del siguiente segmento), acelera con
   atempo hasta max_tempo.
4. Si aun así no cabe, pide a Claude una versión más corta de la frase y la
   resintetiza (hasta SHORTEN_ROUNDS rondas).
5. Control de calidad: los clips con una velocidad anómala para su texto
   (vacíos, cortados, repeticiones) se regeneran una vez.
Lo que siga sin caber o sin pasar el control queda en overflow.log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import statistics
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
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
SHORTEN_ROUNDS = 2
OVERFLOW_EPSILON = 0.05  # excesos menores se consideran redondeo y no se registran
OVERFLOW_TOLERANCE = 0.15  # segundos de exceso que se aceptan sin retraducir
TRIM = (
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse"
)
# Frases sueltas, como los clips reales: así la medida no incluye pausas entre frases
CALIBRATION_SENTENCES = [
    "Hoy vamos a ver cómo funciona este proceso paso a paso.",
    "Primero, conviene entender de dónde viene la idea y por qué es tan importante.",
    "Después veremos algunos ejemplos concretos, con cifras reales.",
    "Al final resumiremos lo más útil para el día a día.",
    "¿Te has preguntado alguna vez qué pasa cuando nadie mira?",
]


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
    text: str = ""  # texto locutado (puede ser una versión acortada de la traducción)


def choose_tempo(duration: float, slot: float, seg_duration: float, min_tempo: float, max_tempo: float) -> float:
    """Factor de atempo: acelera si no cabe; ralentiza solo si min_tempo < 1."""
    if duration > slot:
        return min(duration / slot, max_tempo)
    if min_tempo < 1.0 and duration < seg_duration:
        return max(duration / seg_duration, min_tempo)
    return 1.0


def shorten_target(text: str, clip: Clip, max_tempo: float) -> int:
    """Caracteres que cabrían en el hueco al tempo máximo, con un 5 % de margen."""
    fits = len(text) * clip.slot * max_tempo / clip.raw_duration
    return max(int(fits * 0.95), 1)


def suspicious(clips: list[Clip], min_chars: int = 15) -> list[Clip]:
    """Clips cuya velocidad (caracteres/s) se aleja mucho de la mediana del vídeo."""
    rates = [len(c.text) / c.raw_duration for c in clips if c.raw_duration > 0 and len(c.text) >= min_chars]
    if len(rates) < 3:
        return [c for c in clips if c.raw_duration < 0.15]
    median = statistics.median(rates)
    out = []
    for c in clips:
        if c.raw_duration < 0.15:
            out.append(c)
        elif len(c.text) >= min_chars and not 0.5 * median <= len(c.text) / c.raw_duration <= 1.8 * median:
            out.append(c)
    return out


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


def speaking_rate(work_root: Path, voice: str, rate: str) -> float:
    """Caracteres por segundo de una voz, medidos sintetizando un texto de referencia.

    Se cachea en <work_root>/voice_rates.json para no repetir la medición.
    """
    check_rate(rate)
    cache = work_root / "voice_rates.json"
    rates = json.loads(cache.read_text()) if cache.exists() else {}
    key = f"{voice} {rate}"
    if key in rates:
        return rates[key]

    tmp_dir = work_root / ".calibration"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(text, tmp_dir / f"ref{i}.mp3") for i, text in enumerate(CALIBRATION_SENTENCES)]
    for _, raw in jobs:
        raw.unlink(missing_ok=True)
    asyncio.run(_synthesize_all(jobs, voice, rate))
    total = 0.0
    for _, raw in jobs:
        trimmed = raw.with_suffix(".wav")
        ffmpeg("-i", str(raw), "-af", TRIM, "-ac", "1", "-ar", str(SAMPLE_RATE), str(trimmed))
        total += _wav_duration(trimmed)
    rates[key] = round(sum(len(t) for t, _ in jobs) / total, 2)
    cache.write_text(json.dumps(rates, indent=1))
    log.info(f"Velocidad calibrada de {voice} ({rate}): {rates[key]} car/s")
    return rates[key]


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
    overflow = duration - slot
    return Clip(
        id=seg.id, start=seg.start, slot=round(slot, 3), raw_duration=round(raw_dur, 3),
        tempo=round(tempo, 3), duration=round(duration, 3),
        # atempo deja el clip ajustado al hueco con unos ms de redondeo: eso no es un exceso
        overflow=round(overflow, 3) if overflow > OVERFLOW_EPSILON else 0.0,
        file=f"tts/{final.name}", text=seg.text,
    )


def load_clips(wd: WorkDir) -> list[Clip]:
    return [Clip(**c) for c in json.loads(wd.tts_index.read_text(encoding="utf-8"))]


def _render(
    wd: WorkDir, segments: list[Segment], slots: dict[int, float], settings: Settings, regenerate: bool = False
) -> list[Clip]:
    """Sintetiza (lo que falte en caché) y procesa los segmentos dados."""
    raws = [_raw_path(wd, settings.voice, settings.rate, s.text) for s in segments]
    if regenerate:
        for p in raws:
            p.unlink(missing_ok=True)
    pending = {p: s.text for s, p in zip(segments, raws) if not p.exists()}
    if pending:
        asyncio.run(_synthesize_all([(t, p) for p, t in pending.items()], settings.voice, settings.rate))
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(
            lambda args: _process(args[0], slots[args[0].id], args[1], wd.tts_dir, settings),
            zip(segments, raws),
        ))


def _shorten_overflows(
    wd: WorkDir, clips: dict[int, Clip], originals: dict[int, str], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings,
) -> int:
    """Retraduce y resintetiza los clips que no caben. Devuelve cuántos se acortaron."""
    from . import translate  # import perezoso: translate también importa este módulo

    shortened = set()
    for round_ in range(1, SHORTEN_ROUNDS + 1):
        bad = [c for c in clips.values() if c.overflow > OVERFLOW_TOLERANCE]
        if not bad:
            break
        log.info(f"Ronda {round_} de acortado: {len(bad)} frase(s) no caben, pidiendo versiones más cortas…")
        items = [(c.id, originals[c.id], c.text, shorten_target(c.text, c, settings.max_tempo)) for c in bad]
        new_texts = translate.shorten(items, settings.voice, settings)
        segs = [replace(by_id[i], text=t) for i, t in new_texts.items()]
        for clip in _render(wd, segs, slots, settings):
            clips[clip.id] = clip
        shortened.update(new_texts)
    return len(shortened)


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Clip]:
    segments = load_segments(wd.translation)
    params = {
        "voice": settings.voice,
        "rate": check_rate(settings.rate),
        "min_tempo": settings.min_tempo,
        "max_tempo": settings.max_tempo,
        "shorten": settings.claude_model if settings.shorten else None,
        "texts": [(s.id, s.start, s.text) for s in segments],
    }
    if not force and wd.is_done("tts", params) and wd.tts_index.exists():
        log.info("TTS en caché, lo salto")
        return load_clips(wd)

    asyncio.run(_check_voice(settings.voice))
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    for old in wd.tts_dir.glob("*.wav"):
        old.unlink()

    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, _slots(segments, meta.get("duration")))}
    by_id = {s.id: s for s in segments}
    log.info(f"Voz {settings.voice} ({settings.rate}) · {len(segments)} segmentos")
    clips = {c.id: c for c in _render(wd, segments, slots, settings, regenerate=force)}

    # Control de calidad: regenerar una vez los clips con duración anómala
    bad_qc = suspicious(list(clips.values()))
    if bad_qc:
        log.warning(f"Control de calidad: {len(bad_qc)} clip(s) con duración anómala, regenerando…")
        segs = [replace(by_id[c.id], text=c.text) for c in bad_qc]
        for clip in _render(wd, segs, slots, settings, regenerate=True):
            clips[clip.id] = clip
    still_bad = {c.id for c in suspicious(list(clips.values()))}

    n_short = 0
    if settings.shorten:
        originals = {s.id: s.text for s in load_segments(wd.segments)}
        n_short = _shorten_overflows(wd, clips, originals, slots, by_id, settings)

    result = [clips[s.id] for s in segments]
    wd.tts_index.write_text(
        json.dumps([asdict(c) for c in result], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    overflows = [c for c in result if c.overflow > 0]
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        for c in result:
            if c.overflow > 0:
                f.write(
                    f"#{c.id} @{c.start:.2f}s: dura {c.duration:.2f}s a {c.tempo}x, hueco {c.slot:.2f}s "
                    f"(+{c.overflow:.2f}s) · {c.text}\n"
                )
            if c.id in still_bad:
                f.write(f"#{c.id} @{c.start:.2f}s: duración anómala tras regenerar ({c.raw_duration:.2f}s) · {c.text}\n")

    sped = sum(1 for c in result if c.tempo > 1.0)
    chars_per_s = sum(len(c.text) for c in result) / sum(c.raw_duration for c in result)
    log.info(
        f"Acelerados: {sped} · acortados: {n_short} · no caben: {len(overflows)}"
        + (f" (máx +{max(c.overflow for c in overflows):.2f}s, ver overflow.log)" if overflows else "")
    )
    if still_bad:
        log.warning(f"{len(still_bad)} clip(s) siguen con duración anómala (ver overflow.log)")
    log.info(f"Velocidad de locución medida: {chars_per_s:.1f} caracteres/s")
    wd.mark_done("tts", params)
    return result
