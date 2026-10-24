"""Phase 4: per-segment TTS (edge-tts or a cloned voice) and speed fitting with atempo.

For each translated segment:
1. Synthesize the clip with edge-tts or, with `--tts clone`, with the original
   speaker's cloned voice (cached by voice+text, so editing one sentence only
   regenerates that one).
2. Trim leading and trailing silence and convert to 24 kHz mono wav.
3. If it does not fit its slot (up to the start of the next segment), speed it
   up with atempo up to max_tempo.
4. If it still does not fit, ask Claude for a shorter version of the sentence
   and re-synthesize it (up to SHORTEN_ROUNDS rounds).
5. Quality check: clips whose speed is abnormal for their text (empty, cut off,
   repetitions) are regenerated once. Cloned clips are also transcribed with
   whisper, and a failing one goes down a fallback chain that keeps the voice
   as long as possible: another seed → a shorter sentence → the fixed
   reference (`--clone-ref`) → edge-tts as a last resort.
Whatever still does not fit or fails the check is written to overflow.log.
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
OVERFLOW_EPSILON = 0.05  # smaller overflows are rounding and are not reported
OVERFLOW_TOLERANCE = 0.15  # seconds of overflow accepted without re-translating
TRIM = (
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
    "areverse"
)
# Spanish on purpose: this is what gets synthesized to measure the Spanish voice.
# Separate sentences, like real clips, so the measurement excludes pauses between sentences
CALIBRATION_SENTENCES = [
    "Hoy vamos a ver cómo funciona este proceso paso a paso.",
    "Primero, conviene entender de dónde viene la idea y por qué es tan importante.",
    "Después veremos algunos ejemplos concretos, con cifras reales.",
    "Al final resumiremos lo más útil para el día a día.",
    "¿Te has preguntado alguna vez qué pasa cuando nadie mira?",
]


SEED = 0  # cloned voices: base seed, so a rerun reproduces the same clips


@dataclass(frozen=True)
class Voice:
    """How a clip is spoken: an edge-tts voice or a clone of a reference recording."""

    engine: str  # edge | clone
    name: str  # edge-tts voice; also gives the target Spanish variant
    rate: str
    ref: Path | None = None  # clone: reference recording
    seed: int = SEED
    label: str = "edge"  # recorded in tts.json

    @classmethod
    def edge(cls, settings: Settings) -> Voice:
        return cls("edge", settings.voice, settings.rate)

    @classmethod
    def clone(cls, settings: Settings, ref: Path, label: str = "clone", seed: int = SEED) -> Voice:
        return cls("clone", settings.voice, settings.rate, ref=ref, seed=seed, label=label)


@dataclass
class Clip:
    id: int
    start: float
    slot: float  # seconds available up to the next segment
    raw_duration: float  # duration after trimming silence, before atempo
    tempo: float
    duration: float  # final duration
    overflow: float  # seconds that still do not fit (0 if it fits)
    file: str
    text: str = ""  # spoken text (may be a shortened version of the translation)
    voice: str = "edge"  # Voice.label that produced it


def choose_tempo(duration: float, slot: float, seg_duration: float, min_tempo: float, max_tempo: float) -> float:
    """atempo factor: speed up if it does not fit; slow down only if min_tempo < 1."""
    if duration > slot:
        return min(duration / slot, max_tempo)
    if min_tempo < 1.0 and duration < seg_duration:
        return max(duration / seg_duration, min_tempo)
    return 1.0


def shorten_target(text: str, clip: Clip, max_tempo: float) -> int:
    """Characters that would fit the slot at the maximum tempo, with a 5% margin."""
    fits = len(text) * clip.slot * max_tempo / clip.raw_duration
    return max(int(fits * 0.95), 1)


def suspicious(clips: list[Clip], min_chars: int = 15) -> list[Clip]:
    """Clips whose speed (characters/s) is far from the video's median."""
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
    """Validate the edge-tts rate format: "+0%", "-10%"…"""
    if not re.fullmatch(r"[+-]\d{1,2}%", rate):
        raise SystemExit(f"--rate must look like -10% or +5% (not {rate!r})")
    return rate


def _raw_path(wd: WorkDir, voice: Voice, text: str) -> Path:
    if voice.engine == "clone":
        from . import clone

        raw = f"{clone.MODEL}\n{clone.file_hash(voice.ref)}\n{voice.seed}\n{text}"
        return wd.tts_dir / "raw" / f"{hashlib.sha256(raw.encode()).hexdigest()[:16]}.wav"
    key = hashlib.sha256(f"{voice.name}\n{voice.rate}\n{text}".encode()).hexdigest()[:16]
    return wd.tts_dir / "raw" / f"{key}.mp3"


def _synthesize(jobs: list[tuple[str, Path]], voice: Voice) -> None:
    """Synthesize every (text, path) job with the given voice."""
    if voice.engine == "edge":
        asyncio.run(_synthesize_all(jobs, voice.name, voice.rate))
        return
    from . import clone

    # One GPU model: clips go one after another
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Cloning voice", total=len(jobs))
        for text, path in jobs:
            clone.synthesize(text, voice.ref, voice.seed, path)
            progress.advance(task)


async def _synthesize_all(jobs: list[tuple[str, Path]], voice: str, rate: str) -> None:
    import edge_tts

    sem = asyncio.Semaphore(CONCURRENCY)
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Synthesizing voice", total=len(jobs))

        async def one(text: str, path: Path) -> None:
            async with sem:
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    try:
                        tmp = path.with_suffix(".part")
                        await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
                        tmp.rename(path)
                        break
                    except Exception as e:  # edge-tts does not type its network errors well
                        if attempt == MAX_ATTEMPTS:
                            raise RuntimeError(f"edge-tts failed on {text[:40]!r}: {e}") from e
                        await asyncio.sleep(2 * attempt)
            progress.advance(task)

        await asyncio.gather(*(one(t, p) for t, p in jobs))


async def _check_voice(voice: str) -> None:
    import edge_tts

    voices = {v["ShortName"] for v in await edge_tts.list_voices()}
    if voice not in voices:
        spanish = ", ".join(sorted(v for v in voices if v.startswith("es-")))
        raise SystemExit(f"Voice {voice!r} does not exist. Spanish voices: {spanish}")


def speaking_rate(work_root: Path, voice: str, rate: str) -> float:
    """Characters per second of a voice, measured by synthesizing reference sentences.

    Cached in <work_root>/voice_rates.json so the measurement is not repeated.
    """
    check_rate(rate)
    cache = work_root / "voice_rates.json"
    rates = json.loads(cache.read_text()) if cache.exists() else {}
    key = f"{voice} {rate}"
    if key in rates:
        return rates[key]

    rates[key] = _calibrate(work_root, Voice("edge", voice, rate))
    cache.write_text(json.dumps(rates, indent=1))
    log.info(f"Calibrated rate for {voice} ({rate}): {rates[key]} chars/s")
    return rates[key]


def clone_speaking_rate(work_root: Path, ref: Path) -> float:
    """Characters per second of the voice cloned from `ref`, cached like speaking_rate."""
    from . import clone

    cache = work_root / "voice_rates.json"
    rates = json.loads(cache.read_text()) if cache.exists() else {}
    key = f"{clone.MODEL} {clone.file_hash(ref)}"
    if key not in rates:
        rates[key] = _calibrate(work_root, Voice("clone", "", "", ref=ref))
        cache.write_text(json.dumps(rates, indent=1))
        log.info(f"Calibrated rate for the cloned voice: {rates[key]} chars/s")
    return rates[key]


def voice_rate(wd: WorkDir, settings: Settings) -> float:
    """Speaking rate of the voice the video will be dubbed with."""
    if check_engine(settings.tts) == "clone":
        from . import clone

        return clone_speaking_rate(settings.work_root, clone.reference(wd))
    return speaking_rate(settings.work_root, settings.voice, settings.rate)


def check_engine(engine: str) -> str:
    if engine not in ("edge", "clone"):
        raise SystemExit(f"--tts must be edge or clone (not {engine!r})")
    return engine


def _calibrate(work_root: Path, voice: Voice) -> float:
    """Synthesize the calibration sentences and measure their characters per second."""
    tmp_dir = work_root / ".calibration"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ext = ".mp3" if voice.engine == "edge" else ".raw.wav"
    jobs = [(text, tmp_dir / f"ref{i}{ext}") for i, text in enumerate(CALIBRATION_SENTENCES)]
    for _, raw in jobs:
        raw.unlink(missing_ok=True)
    _synthesize(jobs, voice)
    total = 0.0
    for i, (_, raw) in enumerate(jobs):
        trimmed = tmp_dir / f"ref{i}.wav"
        ffmpeg("-i", str(raw), "-af", TRIM, "-ac", "1", "-ar", str(SAMPLE_RATE), str(trimmed))
        total += _wav_duration(trimmed)
    return round(sum(len(t) for t, _ in jobs) / total, 2)


def _process(seg: Segment, slot: float, raw: Path, out_dir: Path, settings: Settings, label: str) -> Clip:
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
        # atempo fits the clip to the slot with a few ms of rounding: that is not an overflow
        overflow=round(overflow, 3) if overflow > OVERFLOW_EPSILON else 0.0,
        file=f"tts/{final.name}", text=seg.text, voice=label,
    )


def load_clips(wd: WorkDir) -> list[Clip]:
    return [Clip(**c) for c in json.loads(wd.tts_index.read_text(encoding="utf-8"))]


def _render(
    wd: WorkDir, segments: list[Segment], slots: dict[int, float], settings: Settings, voice: Voice,
    regenerate: bool = False,
) -> list[Clip]:
    """Synthesize (whatever is not cached) and process the given segments."""
    raws = [_raw_path(wd, voice, s.text) for s in segments]
    if regenerate:
        for p in raws:
            p.unlink(missing_ok=True)
    pending = {p: s.text for s, p in zip(segments, raws) if not p.exists()}
    if pending:
        _synthesize([(t, p) for p, t in pending.items()], voice)
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(
            lambda args: _process(args[0], slots[args[0].id], args[1], wd.tts_dir, settings, voice.label),
            zip(segments, raws),
        ))


def _render_each(
    wd: WorkDir, jobs: list[tuple[Segment, Voice]], slots: dict[int, float], settings: Settings,
    regenerate: bool = False,
) -> list[Clip]:
    """Like _render, but every segment with its own voice."""
    by_voice: dict[Voice, list[Segment]] = {}
    for seg, voice in jobs:
        by_voice.setdefault(voice, []).append(seg)
    return [
        clip for voice, segs in by_voice.items()
        for clip in _render(wd, segs, slots, settings, voice, regenerate=regenerate)
    ]


def _shorten_overflows(
    wd: WorkDir, clips: dict[int, Clip], originals: dict[int, str], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings, voices: dict[int, Voice],
) -> int:
    """Re-translate and re-synthesize clips that do not fit. Return how many were shortened."""
    from . import translate  # lazy import: translate also imports this module

    shortened = set()
    for round_ in range(1, SHORTEN_ROUNDS + 1):
        bad = [c for c in clips.values() if c.overflow > OVERFLOW_TOLERANCE]
        if not bad:
            break
        log.info(f"Shortening round {round_}: {len(bad)} sentence(s) do not fit, asking for shorter versions…")
        items = [(c.id, originals[c.id], c.text, shorten_target(c.text, c, settings.max_tempo)) for c in bad]
        new_texts = translate.shorten(items, settings.voice, settings)
        jobs = [(replace(by_id[i], text=t), voices[i]) for i, t in new_texts.items()]
        for clip in _render_each(wd, jobs, slots, settings):
            clips[clip.id] = clip
        shortened.update(new_texts)
    return len(shortened)


def _clone_failures(wd: WorkDir, ids: set[int], clips: dict[int, Clip], settings: Settings) -> set[int]:
    """Cloned clips among `ids` with an abnormal duration or that whisper can't understand."""
    from . import clone

    bad = {c.id for c in suspicious(list(clips.values())) if c.id in ids}
    rest = [(i, wd.path / clips[i].file, clips[i].text) for i in sorted(ids - bad)]
    return bad | (clone.unintelligible(rest, settings.whisper_model) if rest else set())


def _repair_clones(
    wd: WorkDir, clips: dict[int, Clip], voices: dict[int, Voice], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings,
) -> set[int]:
    """Redo the cloned clips that fail the quality check without switching voices mid-video.

    Fallback chain, each step only for the clips the previous one could not fix:
    another seed → a sentence shortened by Claude → the fixed reference
    (--clone-ref) → edge-tts. Returns the ids that ended up with edge-tts.
    """
    from . import translate  # lazy import: translate also imports this module

    bad = _clone_failures(wd, set(clips), clips, settings)
    steps = ["another seed", "a shorter sentence", "the fixed reference", "edge-tts"]
    for step in steps:
        if not bad:
            return set()
        if step == "a shorter sentence" and not settings.shorten:
            continue
        if step == "the fixed reference" and not settings.clone_ref:
            continue
        log.warning(f"Quality check: {len(bad)} cloned clip(s) failed, retrying with {step}…")
        texts = {i: clips[i].text for i in bad}
        if step == "another seed":
            new_voices = {i: replace(voices[i], seed=voices[i].seed + 1, label="clone (seed+1)") for i in bad}
        elif step == "a shorter sentence":
            originals = {s.id: s.text for s in load_segments(wd.segments)}
            items = [(i, originals[i], texts[i], max(int(len(texts[i]) * 0.85), 1)) for i in sorted(bad)]
            texts = translate.shorten(items, settings.voice, settings)
            new_voices = {i: replace(voices[i], label="clone (shortened)") for i in bad}
        elif step == "the fixed reference":
            new_voices = {i: Voice.clone(settings, settings.clone_ref, label="clone (fixed reference)") for i in bad}
        else:
            new_voices = {i: Voice.edge(settings) for i in bad}
        jobs = [(replace(by_id[i], text=texts[i]), new_voices[i]) for i in sorted(bad)]
        for clip in _render_each(wd, jobs, slots, settings):
            clips[clip.id] = clip
        voices.update(new_voices)
        if step == "edge-tts":
            return bad
        bad = _clone_failures(wd, bad, clips, settings)
    return set()


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Clip]:
    from . import clone

    segments = load_segments(wd.translation)
    engine = check_engine(settings.tts)
    ref = clone.reference(wd) if engine == "clone" else None
    params = {
        "voice": settings.voice,
        "rate": check_rate(settings.rate),
        "min_tempo": settings.min_tempo,
        "max_tempo": settings.max_tempo,
        "shorten": settings.claude_model if settings.shorten else None,
        "texts": [(s.id, s.start, s.text) for s in segments],
    }
    if engine == "clone":
        if settings.clone_ref and not settings.clone_ref.exists():
            raise SystemExit(f"--clone-ref {settings.clone_ref} does not exist")
        params |= {
            "tts": f"{clone.MODEL} {clone.file_hash(ref)}",
            "clone_ref": clone.file_hash(settings.clone_ref) if settings.clone_ref else None,
            "qc_whisper": settings.whisper_model,
        }
    if not force and wd.is_done("tts", params) and wd.tts_index.exists():
        log.info("TTS cached, skipping")
        return load_clips(wd)

    asyncio.run(_check_voice(settings.voice))  # edge-tts is also the cloned voice's last resort
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    for old in wd.tts_dir.glob("*.wav"):
        old.unlink()

    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, _slots(segments, meta.get("duration")))}
    by_id = {s.id: s for s in segments}
    voice = Voice.clone(settings, ref) if engine == "clone" else Voice.edge(settings)
    voices = {s.id: voice for s in segments}
    if engine == "clone":
        log.info(f"Cloned voice ({clone.MODEL}) · {len(segments)} segments")
    else:
        log.info(f"Voice {settings.voice} ({settings.rate}) · {len(segments)} segments")
    clips = {c.id: c for c in _render(wd, segments, slots, settings, voice, regenerate=force)}

    fell_back: set[int] = set()
    if engine == "clone":
        fell_back = _repair_clones(wd, clips, voices, slots, by_id, settings)
    else:
        # Quality check: regenerate clips with abnormal duration once
        bad_qc = suspicious(list(clips.values()))
        if bad_qc:
            log.warning(f"Quality check: {len(bad_qc)} clip(s) with abnormal duration, regenerating…")
            segs = [replace(by_id[c.id], text=c.text) for c in bad_qc]
            for clip in _render(wd, segs, slots, settings, voice, regenerate=True):
                clips[clip.id] = clip
    still_bad = {c.id for c in suspicious(list(clips.values()))}

    n_short = 0
    if settings.shorten:
        originals = {s.id: s.text for s in load_segments(wd.segments)}
        n_short = _shorten_overflows(wd, clips, originals, slots, by_id, settings, voices)

    result = [clips[s.id] for s in segments]
    wd.tts_index.write_text(
        json.dumps([asdict(c) for c in result], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    overflows = [c for c in result if c.overflow > 0]
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        for c in result:
            if c.overflow > 0:
                f.write(
                    f"#{c.id} @{c.start:.2f}s: lasts {c.duration:.2f}s at {c.tempo}x, slot {c.slot:.2f}s "
                    f"(+{c.overflow:.2f}s) · {c.text}\n"
                )
            if c.id in still_bad:
                f.write(f"#{c.id} @{c.start:.2f}s: abnormal duration after regenerating ({c.raw_duration:.2f}s) · {c.text}\n")
            if c.id in fell_back:
                f.write(f"#{c.id} @{c.start:.2f}s: cloned voice failed the quality check, used edge-tts · {c.text}\n")

    sped = sum(1 for c in result if c.tempo > 1.0)
    chars_per_s = sum(len(c.text) for c in result) / sum(c.raw_duration for c in result)
    log.info(
        f"Sped up: {sped} · shortened: {n_short} · do not fit: {len(overflows)}"
        + (f" (max +{max(c.overflow for c in overflows):.2f}s, see overflow.log)" if overflows else "")
    )
    if engine == "clone":
        repaired = sum(1 for c in result if c.voice not in ("clone", "edge"))
        log.info(f"Cloned clips redone by the quality check: {repaired} · fell back to edge-tts: {len(fell_back)}")
    if fell_back:
        log.warning(f"{len(fell_back)} clip(s) use edge-tts instead of the cloned voice (see overflow.log)")
    if still_bad:
        log.warning(f"{len(still_bad)} clip(s) still have an abnormal duration (see overflow.log)")
    log.info(f"Measured speaking rate: {chars_per_s:.1f} chars/s")
    wd.mark_done("tts", params)
    return result
