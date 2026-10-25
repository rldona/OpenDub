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
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, TimeElapsedColumn

from . import reference, style
from .config import Settings
from .log import Progress, console, log
from .media import ffmpeg
from .models import Segment, load_segments
from .spoken import spell_numbers
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
# Cloned voices are also measured on short and long sentences, to separate what
# every clip takes regardless of its length (onset, ending) from the speaking rate
CALIBRATION_EXTRA = [
    "Sí, claro.",
    "Vamos allá.",
    "Y eso es todo por ahora.",
    "Cuando lo pruebes tú mismo verás que, con un poco de práctica y algo de paciencia, "
    "el resultado mejora muchísimo de una semana a otra.",
]


@dataclass(frozen=True)
class Pace:
    """How long a voice takes to say a text: a fixed `overhead` per clip plus `cps` chars/s.

    For IndexTTS a clip took 1.5 s besides its characters, so with a plain rate short
    sentences were planned at half their real length.
    """

    cps: float
    overhead: float = 0.0

    def seconds(self, chars: int) -> float:
        return self.overhead + chars / self.cps

    def max_chars(self, slot: float) -> int:
        """Characters that fit `slot`; never below 30% of the plain rate's, for tiny slots."""
        return max(round((slot - self.overhead) * self.cps), round(0.3 * slot * self.cps), 1)


SEED = 0  # cloned voices: base seed, so a rerun reproduces the same clips


@dataclass(frozen=True)
class Voice:
    """How a clip is spoken: an edge-tts voice or a clone of a reference recording."""

    engine: str  # edge | chatterbox | indextts | cosyvoice
    name: str  # edge-tts voice; also gives the target Spanish variant
    rate: str
    ref: Path | None = None  # cloned voices: reference recording
    seed: int = SEED
    label: str = "edge"  # recorded in tts.json
    factor: float = 1.0  # engines with a native duration control: duration factor (<1 = shorter)

    @classmethod
    def edge(cls, settings: Settings) -> Voice:
        return cls("edge", settings.voice, settings.rate)

    @classmethod
    def clone(cls, settings: Settings, ref: Path, label: str | None = None, seed: int = SEED) -> Voice:
        engine = resolve_engine(settings, ref)
        return cls(engine, settings.voice, settings.rate, ref=ref, seed=seed, label=label or engine)


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
    factor: float = 1.0  # duration factor it was spoken with (native duration control)


def choose_tempo(duration: float, slot: float, seg_duration: float, min_tempo: float, max_tempo: float) -> float:
    """atempo factor: speed up if it does not fit; slow down only if min_tempo < 1."""
    if duration > slot:
        return min(duration / slot, max_tempo)
    if min_tempo < 1.0 and duration < seg_duration:
        return max(duration / seg_duration, min_tempo)
    return 1.0


def shorten_target(text: str, clip: Clip, max_tempo: float, overhead: float = 0.0) -> int:
    """Characters that would fit the slot at the maximum tempo, with a 5% margin.

    `overhead`: seconds of the clip that don't depend on its length (see Pace).
    """
    fits = len(text) * (clip.slot * max_tempo - overhead) / max(clip.raw_duration - overhead, 0.1)
    return max(int(fits * 0.95), 1)


def spoken_len(text: str) -> int:
    """Characters of a text as it is said: "192" counts as "ciento noventa y dos"."""
    return len(spell_numbers(text))


# Texts this short ("Yo", "Sí") can't be judged by whisper (one misheard sound is half the
# text) nor shortened (Claude turned "Yo" into "Y"): only their duration is checked
TINY_CHARS = 3


def tiny(text: str) -> bool:
    return spoken_len(text.strip(" .,;:!?¡¿«»\"'…-")) <= TINY_CHARS


def suspicious(clips: list[Clip], min_chars: int = 15) -> list[Clip]:
    """Clips whose speed (characters/s) is far from the video's median.

    Short texts don't count towards the median; they are flagged when cut off
    (under 0.15 s) or far too long for what they say (a garbled "Yo" of 3 s).
    """
    # duration_factor shortens clips on purpose: judge them at the speed they'd have at 1.0
    natural = lambda c: spoken_len(c.text) * c.factor / c.raw_duration
    rates = [natural(c) for c in clips if c.raw_duration > 0 and len(c.text) >= min_chars]
    if len(rates) < 3:
        return [c for c in clips if c.raw_duration < 0.15 or _too_long(c, min_chars)]
    median = statistics.median(rates)
    out = []
    for c in clips:
        if c.raw_duration < 0.15 or _too_long(c, min_chars):
            out.append(c)
        elif len(c.text) >= min_chars and not 0.5 * median <= natural(c) <= 1.8 * median:
            out.append(c)
    return out


def _too_long(c: Clip, min_chars: int) -> bool:
    """A short text that takes far longer than even a slow voice would (1 s plus 5 chars/s)."""
    return len(c.text) < min_chars and c.raw_duration / c.factor > 1.0 + spoken_len(c.text) / 5


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
    if voice.engine != "edge":
        from . import clone

        # "spoken-v1": cloned voices get figures written out (spoken.py); older clips said them wrong
        raw = f"{engine_model(voice.engine)}\n{clone.file_hash(voice.ref)}\n{voice.seed}\nspoken-v1\n{text}"
        if native_duration(voice.engine):
            raw += f"\n{voice.factor:.3f}"
        return wd.tts_dir / "raw" / f"{hashlib.sha256(raw.encode()).hexdigest()[:16]}.wav"
    key = hashlib.sha256(f"{voice.name}\n{voice.rate}\n{text}".encode()).hexdigest()[:16]
    return wd.tts_dir / "raw" / f"{key}.mp3"


def _synthesize(jobs: list[tuple[str, Path]], voice: Voice, settings: Settings) -> None:
    """Synthesize every (text, path) job with the given voice."""
    _synthesize_jobs([(text, path, voice) for text, path in jobs], settings)


def _synthesize_jobs(jobs: list[tuple[str, Path, Voice]], settings: Settings) -> None:
    """Synthesize (text, path, voice) jobs, each with its own voice.

    All cloned clips share one progress bar, whatever their voice or
    duration_factor (IndexTTS gives nearly every clip its own), so the bar
    reflects the whole batch instead of restarting per group.
    """
    edge: dict[tuple[str, str], list[tuple[str, Path]]] = {}
    cloned = []
    for text, path, voice in jobs:
        if voice.engine == "edge":
            edge.setdefault((voice.name, voice.rate), []).append((text, path))
        else:
            cloned.append((text, path, voice))
    for (name, rate), group in edge.items():
        asyncio.run(_synthesize_all(group, name, rate))
    if not cloned:
        return
    from . import clone, cosyvoice, indextts

    # One GPU model: clips go one after another
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Cloning voice", total=len(cloned))
        # Chatterbox clips go to its process pool, several at a time (clone.synthesize_batch)
        batch = [(spell_numbers(text), voice.ref, voice.seed, path) for text, path, voice in cloned
                 if voice.engine == "chatterbox"]
        if batch:
            clone.synthesize_batch(batch, settings.work_root / "chatterbox.log", lambda: progress.advance(task))
        for text, path, voice in cloned:
            said = spell_numbers(text)  # cloned voices misread figures and "2x2"
            if voice.engine == "chatterbox":
                continue
            if voice.engine == "indextts":
                indextts.synthesize(settings.indextts_dir, settings.work_root / "indextts.log",
                                    said, voice.ref, path, voice.factor, voice.seed)
            elif voice.engine == "cosyvoice":
                cosyvoice.synthesize(settings.cosyvoice_dir, settings.work_root / "cosyvoice.log",
                                     said, voice.ref, path, voice.factor, voice.seed)
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

    samples = _calibrate(Settings(work_root=work_root), Voice("edge", voice, rate), CALIBRATION_SENTENCES)
    rates[key] = round(sum(c for c, _ in samples) / sum(s for _, s in samples), 2)
    cache.write_text(json.dumps(rates, indent=1))
    log.info(f"Calibrated rate for {voice} ({rate}): {rates[key]} chars/s")
    return rates[key]


def cloned_speaking_rate(settings: Settings, voice: Voice) -> Pace:
    """Pace of a cloned voice (per-clip overhead and chars/s), cached like speaking_rate.

    Engines with a native duration control are measured at their
    CALIBRATION_FACTOR, the pace their clips are planned around (IndexTTS 0.85,
    CosyVoice 1.0); Chatterbox at its only pace.
    """
    factor = calibration_factor(voice.engine)
    cache = settings.work_root / "voice_rates.json"
    rates = json.loads(cache.read_text()) if cache.exists() else {}
    key = cloned_rate_key(voice.engine, voice.ref)
    if key not in rates:
        samples = _calibrate(settings, replace(voice, factor=factor, seed=SEED), CALIBRATION_SENTENCES + CALIBRATION_EXTRA)
        rates[key] = asdict(fit_pace(samples))
        cache.write_text(json.dumps(rates, indent=1))
        log.info(f"Calibrated the cloned voice ({voice.engine}): {rates[key]['overhead']} s per clip "
                 f"+ {rates[key]['cps']} chars/s")
    return Pace(**rates[key])


def fit_pace(samples: list[tuple[int, float]]) -> Pace:
    """Fit seconds = overhead + chars / cps over (chars, seconds) samples, robust to a bad clip.

    A cloned voice sometimes garbles a calibration sentence (IndexTTS once took 8 s to
    say "Vamos allá."), which drags a least-squares fit far off: the worst sample is
    dropped while it is more than 1 s off (up to 2, keeping at least 5), and the
    overhead is capped at MAX_OVERHEAD_S, the most measured on real clips was 1.5 s.
    """
    points = list(samples)
    pace = _least_squares(points)
    for _ in range(2):
        if len(points) <= 5:
            break
        worst = max(points, key=lambda p: abs(p[1] - pace.seconds(p[0])))
        if abs(worst[1] - pace.seconds(worst[0])) <= 1.0:
            break
        points.remove(worst)
        pace = _least_squares(points)
    if pace.overhead > MAX_OVERHEAD_S:
        chars = sum(c for c, _ in points)
        speech = sum(s - MAX_OVERHEAD_S for _, s in points)
        pace = Pace(round(chars / speech, 2), MAX_OVERHEAD_S) if speech > 0 else _plain_rate(points)
    return pace


MAX_OVERHEAD_S = 2.5


def _plain_rate(points: list[tuple[int, float]]) -> Pace:
    return Pace(round(sum(c for c, _ in points) / sum(s for _, s in points), 2))


def _least_squares(points: list[tuple[int, float]]) -> Pace:
    n = len(points)
    mean_c = sum(c for c, _ in points) / n
    mean_s = sum(s for _, s in points) / n
    var = sum((c - mean_c) ** 2 for c, _ in points)
    slope = sum((c - mean_c) * (s - mean_s) for c, s in points) / var if var else 0.0
    overhead = mean_s - slope * mean_c
    if slope <= 0 or overhead < 0:  # degenerate: fall back to a plain rate
        return _plain_rate(points)
    return Pace(round(1 / slope, 2), round(overhead, 3))


def cloned_rate_key(engine: str, ref: Path) -> str:
    """Key of a cloned voice's speaking rate in voice_rates.json."""
    from . import clone

    factor = calibration_factor(engine)
    # "pace-v2": overhead + rate (Pace) with the outlier-robust fit; older entries hold a plain
    # rate ("" ) or a fit a garbled calibration clip could skew ("pace")
    return f"{engine_model(engine)} {clone.file_hash(ref)}" + (f" @{factor}" if factor != 1.0 else "") + " pace-v2"


def cached_rate(work_root: Path, engine: str, ref: Path | None, voice: str, rate: str) -> Pace | None:
    """The calibrated pace if it was already measured; never calibrates."""
    cache = work_root / "voice_rates.json"
    if not cache.exists():
        return None
    rates = json.loads(cache.read_text())
    if engine == "edge":
        cps = rates.get(f"{voice} {rate}")
        return Pace(cps) if cps else None
    entry = rates.get(cloned_rate_key(engine, ref)) if ref and ref.exists() else None
    return Pace(**entry) if entry else None


def voice_rate(wd: WorkDir, settings: Settings) -> Pace:
    """Pace of the voice the video will be dubbed with."""
    if settings.tts == "clone":  # Voice.clone resolves the engine (auto needs the reference)
        return cloned_speaking_rate(settings, Voice.clone(settings, reference.reference(wd)))
    resolve_engine(settings)  # validates --tts
    return Pace(speaking_rate(settings.work_root, settings.voice, settings.rate))


CLONE_ENGINES = ("chatterbox", "indextts", "cosyvoice")  # --engine; Settings.engine defaults to chatterbox
# Engines that scale a clip's duration themselves (a duration factor): their clips are
# fitted to the slot natively, down to --min-factor, before shortening and atempo
NATIVE_DURATION = ("indextts", "cosyvoice")


AUTO_F0_HZ = 165.0  # --engine auto: references below it get IndexTTS, the rest Chatterbox


def resolve_engine(settings: Settings, ref: Path | None = None) -> str:
    """The engine that speaks: edge for --tts edge, the --engine choice for --tts clone.

    `auto` picks by the reference's mean F0 (it needs `ref`): IndexTTS for low
    voices, Chatterbox for high ones, which is what was preferred by ear on the
    two benchmark videos (one voice of each). A rule from two voices, hence
    opt-in; Chatterbox when the F0 can't be measured.
    """
    if settings.tts not in ("edge", "clone"):
        raise SystemExit(f"--tts must be edge or clone (not {settings.tts!r})")
    if settings.tts == "edge":
        return "edge"
    if settings.engine not in (*CLONE_ENGINES, "auto"):
        raise SystemExit(f"--engine must be {', '.join(CLONE_ENGINES)} or auto (not {settings.engine!r})")
    if settings.engine != "auto":
        return settings.engine
    if ref is None:
        raise ValueError("--engine auto needs the reference to measure its pitch")
    f0 = reference.mean_f0(ref)
    return "indextts" if f0 is not None and f0 < AUTO_F0_HZ else "chatterbox"


def native_duration(engine: str) -> bool:
    return engine in NATIVE_DURATION


def _engine_module(engine: str):
    from . import clone, cosyvoice, indextts

    return {"chatterbox": clone, "indextts": indextts, "cosyvoice": cosyvoice}[engine]


def calibration_factor(engine: str) -> float:
    return _engine_module(engine).CALIBRATION_FACTOR if native_duration(engine) else 1.0


def min_factor(engine: str) -> float:
    """The lowest duration factor an engine is asked for (below --min-factor, a last resort)."""
    return _engine_module(engine).MIN_FACTOR


def engine_model(engine: str) -> str:
    return _engine_module(engine).MODEL


def _calibrate(settings: Settings, voice: Voice, sentences: list[str]) -> list[tuple[int, float]]:
    """Synthesize the sentences and measure each one: (spoken characters, seconds without silence)."""
    tmp_dir = settings.work_root / ".calibration"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ext = ".mp3" if voice.engine == "edge" else ".raw.wav"
    jobs = [(text, tmp_dir / f"ref{i}{ext}") for i, text in enumerate(sentences)]
    for _, raw in jobs:
        raw.unlink(missing_ok=True)
    _synthesize(jobs, voice, settings)
    samples = []
    for i, (text, raw) in enumerate(jobs):
        trimmed = tmp_dir / f"ref{i}.wav"
        ffmpeg("-i", str(raw), "-af", TRIM, "-ac", "1", "-ar", str(SAMPLE_RATE), str(trimmed))
        samples.append((spoken_len(text), _wav_duration(trimmed)))
    return samples


def _process(seg: Segment, slot: float, raw: Path, out_dir: Path, settings: Settings, voice: Voice) -> Clip:
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
        file=f"tts/{final.name}", text=seg.text, voice=voice.label, factor=voice.factor,
    )


def load_clips(wd: WorkDir) -> list[Clip]:
    data = json.loads(wd.tts_index.read_text(encoding="utf-8"))
    return [Clip(**c) for c in (data["clips"] if isinstance(data, dict) else data)]  # list: older runs


def _render(
    wd: WorkDir, segments: list[Segment], slots: dict[int, float], settings: Settings, voice: Voice,
    regenerate: bool = False,
) -> list[Clip]:
    """Synthesize (whatever is not cached) and process the given segments."""
    return _render_jobs(wd, [(s, voice) for s in segments], slots, settings, regenerate=regenerate)


def _render_jobs(
    wd: WorkDir, jobs: list[tuple[Segment, Voice]], slots: dict[int, float], settings: Settings,
    regenerate: bool = False,
) -> list[Clip]:
    """Synthesize (whatever is not cached) and process segments, each with its own voice, in one pass."""
    raws = [_raw_path(wd, voice, seg.text) for seg, voice in jobs]
    if regenerate:
        for p in raws:
            p.unlink(missing_ok=True)
    pending: dict[Path, tuple[str, Path, Voice]] = {}
    for (seg, voice), raw in zip(jobs, raws):
        if not raw.exists():
            pending.setdefault(raw, (seg.text, raw, voice))
    if pending:
        _synthesize_jobs(list(pending.values()), settings)
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(
            lambda args: _process(args[0][0], slots[args[0][0].id], args[1], wd.tts_dir, settings, args[0][1]),
            zip(jobs, raws),
        ))


def _render_each(
    wd: WorkDir, jobs: list[tuple[Segment, Voice]], slots: dict[int, float], settings: Settings,
    regenerate: bool = False,
) -> list[Clip]:
    """Like _render, but every segment with its own voice (native-duration clips fitted to their slot)."""
    jobs = _predict_factors(jobs, slots, settings)
    clips = _render_jobs(wd, jobs, slots, settings, regenerate=regenerate)
    return _fit_native(wd, clips, jobs, slots, settings)


def _fit_native(
    wd: WorkDir, clips: list[Clip], jobs: list[tuple[Segment, Voice]], slots: dict[int, float], settings: Settings,
) -> list[Clip]:
    """Re-speak the native-duration clips that overflow their slot with a measured duration factor.

    The first pass already used a factor predicted from the calibrated speaking
    rate; the factor scales the duration almost exactly (IndexTTS's
    duration_factor, CosyVoice's speed), so one measured correction is enough.
    Never below --min-factor: past it the sentence is shortened first
    (_shorten_overflows), and only then compressed further (_below_floor).
    """
    from . import engines

    voices = {seg.id: voice for seg, voice in jobs}
    segs = {seg.id: seg for seg, _ in jobs}
    redo = []
    for c in clips:
        v = voices[c.id]
        if native_duration(v.engine) and c.raw_duration > slots[c.id]:
            factor = engines.fit_factor(c.raw_duration, slots[c.id], v.factor, floor=min(settings.min_factor, v.factor))
            if factor < v.factor - 0.01:
                redo.append((segs[c.id], replace(v, factor=factor)))
    if not redo:
        return clips
    by_id = {c.id: c for c in clips}
    for clip in _render_jobs(wd, redo, slots, settings):
        by_id[clip.id] = clip
    return [by_id[c.id] for c in clips]


def _predict_factors(
    jobs: list[tuple[Segment, Voice]], slots: dict[int, float], settings: Settings,
) -> list[tuple[Segment, Voice]]:
    """Give native-duration jobs the factor their calibrated speaking rate predicts for the slot.

    The slowest factor that fits, between --min-factor and 1.0 (natural pace):
    clips with room are not compressed just because IndexTTS is calibrated at 0.85.
    """
    from . import engines

    out = []
    for seg, voice in jobs:
        if native_duration(voice.engine):
            cal = calibration_factor(voice.engine)
            expected = cloned_speaking_rate(settings, voice).seconds(spoken_len(seg.text))  # seconds at `cal`
            factor = engines.fit_factor(expected, slots[seg.id], cal, floor=settings.min_factor, ceiling=1.0)
            voice = replace(voice, factor=factor)
        out.append((seg, voice))
    return out


def _clip_overhead(clip: Clip, voice: Voice, settings: Settings) -> float:
    """Seconds of this clip that don't depend on its length (cloned voices' calibrated overhead)."""
    if voice.engine == "edge":
        return 0.0
    overhead = cloned_speaking_rate(settings, voice).overhead
    return overhead * clip.factor / calibration_factor(voice.engine)


def _needs_shortening(clip: Clip, voice: Voice) -> bool:
    """Native duration: it doesn't fit at --min-factor, before atempo. Others: not even after atempo."""
    if native_duration(voice.engine):
        return clip.raw_duration - clip.slot > OVERFLOW_TOLERANCE
    return clip.overflow > OVERFLOW_TOLERANCE


def _below_floor(
    wd: WorkDir, clips: dict[int, Clip], voices: dict[int, Voice], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings, only: set[int] | None = None,
) -> set[int]:
    """Last step for native-duration clips that don't fit even shortened: compress below --min-factor.

    Down to the engine's MIN_FACTOR; atempo covers whatever is still left.
    Returns the ids compressed this way (they go to overflow.log).
    """
    from . import engines

    jobs = []
    for c in clips.values():
        if only is not None and c.id not in only:
            continue
        v = voices[c.id]
        if native_duration(v.engine) and c.raw_duration > c.slot:
            factor = engines.fit_factor(c.raw_duration, c.slot, c.factor, floor=min_factor(v.engine))
            if factor < c.factor - 0.01:
                jobs.append((replace(by_id[c.id], text=c.text), replace(v, factor=factor)))
    for clip in _render_jobs(wd, jobs, slots, settings):
        clips[clip.id] = clip
    # a last correction that stays above the floor is routine; only the ones below it are reported
    return {seg.id for seg, voice in jobs if voice.factor < settings.min_factor}


def _shorten_overflows(
    wd: WorkDir, clips: dict[int, Clip], originals: dict[int, str], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings, voices: dict[int, Voice],
    only: set[int] | None = None, fixed: set[int] = frozenset(),
) -> int:
    """Re-translate and re-synthesize clips that do not fit. Return how many were shortened.

    `only`: just these clips (a retouch). `fixed`: hand-edited texts, never rewritten:
    they are compressed (duration factor, atempo) as far as that goes instead.
    """
    from . import translate  # lazy import: translate also imports this module

    shortened = set()
    for round_ in range(1, SHORTEN_ROUNDS + 1):
        bad = [c for c in clips.values() if (only is None or c.id in only) and c.id not in fixed
               and _needs_shortening(c, voices[c.id]) and not tiny(c.text)]
        if not bad:
            break
        log.info(f"Shortening round {round_}: {len(bad)} sentence(s) do not fit, asking for shorter versions…")
        # native-duration engines aim to fit without atempo: the target leaves it out
        items = [(c.id, originals[c.id], c.text,
                  shorten_target(c.text, c, 1.0 if native_duration(voices[c.id].engine) else settings.max_tempo,
                                 _clip_overhead(c, voices[c.id], settings)))
                 for c in bad]
        new_texts = translate.shorten(items, settings.voice, settings, style.load(settings.work_root, wd.path,
                                                                                   settings.style_file))
        jobs = [(replace(by_id[i], text=t), voices[i]) for i, t in new_texts.items()]
        for clip in _render_each(wd, jobs, slots, settings):
            clips[clip.id] = clip
        shortened.update(new_texts)
    return len(shortened)


def _clone_failures(wd: WorkDir, ids: set[int], clips: dict[int, Clip], settings: Settings) -> set[int]:
    """Cloned clips among `ids` with an abnormal duration or that whisper can't understand."""
    from . import clone

    bad = {c.id for c in suspicious(list(clips.values())) if c.id in ids}
    rest = [(i, wd.path / clips[i].file, clips[i].text) for i in sorted(ids - bad) if not tiny(clips[i].text)]
    return bad | (clone.unintelligible(rest, settings.whisper_model) if rest else set())


def _repair_clones(
    wd: WorkDir, clips: dict[int, Clip], voices: dict[int, Voice], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings, only: set[int] | None = None, fixed: set[int] = frozenset(),
) -> set[int]:
    """Redo the cloned clips that fail the quality check without switching voices mid-video.

    Fallback chain, each step only for the clips the previous one could not fix:
    another seed → a sentence shortened by Claude → the fixed reference
    (--clone-ref) → edge-tts. Returns the ids that ended up with edge-tts.

    `only`: check just these clips (a retouch), judged against the whole video's
    speed. `fixed`: hand-edited texts, which skip the shorter-sentence step.
    """
    from . import translate  # lazy import: translate also imports this module

    bad = _clone_failures(wd, set(clips) if only is None else only, clips, settings)
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
            new_voices = {i: replace(voices[i], seed=voices[i].seed + 1, label=f"{voices[i].engine} (seed+1)")
                          for i in bad}
        elif step == "a shorter sentence":
            originals = {s.id: s.text for s in load_segments(wd.segments)}
            items = [(i, originals[i], texts[i], max(int(len(texts[i]) * 0.85), 1)) for i in sorted(bad)
                     if not tiny(texts[i]) and i not in fixed]
            if not items:
                continue
            st = style.load(settings.work_root, wd.path, settings.style_file)
            texts = {**texts, **translate.shorten(items, settings.voice, settings, st)}
            new_voices = {i: replace(voices[i], label=f"{voices[i].engine} (shortened)") for i, *_ in items}
        elif step == "the fixed reference":
            new_voices = {i: replace(voices[i], ref=settings.clone_ref, seed=SEED,
                                     label=f"{voices[i].engine} (fixed reference)") for i in bad}
        else:
            new_voices = {i: Voice.edge(settings) for i in bad}
        redo = set(new_voices)  # a tiny or hand-edited text skips the shorter-sentence step as it is
        jobs = [(replace(by_id[i], text=texts[i]), new_voices[i]) for i in sorted(redo)]
        for clip in _render_each(wd, jobs, slots, settings):
            clips[clip.id] = clip
        voices.update(new_voices)
        if step == "edge-tts":
            return bad
        bad = _clone_failures(wd, redo, clips, settings) | (bad - redo)
    return set()


def takes(wd: WorkDir) -> dict[int, int]:
    """The seed each sentence asked for another take was last spoken with (takes.json)."""
    path = wd.path / "takes.json"
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()} if path.exists() else {}


def hand_edited(wd: WorkDir) -> set[int]:
    """Sentences edited from the web: their text is never rewritten shorter."""
    if not wd.translation_edits.exists():
        return set()
    return {int(k) for k in json.loads(wd.translation_edits.read_text(encoding="utf-8"))}


def _index(wd: WorkDir) -> dict:
    data = json.loads(wd.tts_index.read_text(encoding="utf-8"))
    return {"engine": None, "clips": data} if isinstance(data, list) else data


def pending_edits(wd: WorkDir) -> set[int]:
    """Sentences whose translation changed since the latest dub: what a retouch speaks again.

    tts.json keeps the translation each clip was made from ("sources"); dubs made
    before it did compare the hand edits with what their clips say.
    """
    if not (wd.tts_index.exists() and wd.translation.exists()):
        return set()
    index = _index(wd)
    texts = {s.id: s.text for s in load_segments(wd.translation)}
    sources = index.get("sources")
    if sources is not None:
        return {i for i, text in texts.items() if sources.get(str(i)) != text}
    said = {c["id"]: c.get("text") for c in index.get("clips") or []}
    return {i for i in hand_edited(wd) if i in texts and texts[i] != said.get(i)}


def _params(settings: Settings, segments: list[Segment], engine: str, ref: Path | None,
            seeds: dict[int, int]) -> dict:
    """What a TTS run depends on: the cache key of the phase."""
    from . import clone

    params = {
        "voice": settings.voice,
        "rate": check_rate(settings.rate),
        "min_tempo": settings.min_tempo,
        "max_tempo": settings.max_tempo,
        "shorten": settings.claude_model if settings.shorten else None,
        "texts": [(s.id, s.start, s.text) for s in segments],
    }
    if ref is not None:
        if settings.clone_ref and not settings.clone_ref.exists():
            raise SystemExit(f"--clone-ref {settings.clone_ref} does not exist")
        params |= {
            "tts": f"{engine_model(engine)} {clone.file_hash(ref)}",
            "clone_ref": clone.file_hash(settings.clone_ref) if settings.clone_ref else None,
            "qc_whisper": settings.whisper_model,
        }
        if native_duration(engine):
            params["min_factor"] = settings.min_factor
    if seeds:  # only then: dubs without takes keep their cache
        params["takes"] = sorted(seeds.items())
    return params


def _issue_lines(c: Clip, still_bad: set[int], fell_back: set[int], below_floor: set[int], floor: float) -> list[str]:
    """overflow.log lines of one clip (web/videos.py parses them)."""
    lines = []
    if c.overflow > 0:
        lines.append(f"#{c.id} @{c.start:.2f}s: lasts {c.duration:.2f}s at {c.tempo}x, slot {c.slot:.2f}s "
                     f"(+{c.overflow:.2f}s) · {c.text}\n")
    if c.id in still_bad:
        lines.append(f"#{c.id} @{c.start:.2f}s: abnormal duration after regenerating ({c.raw_duration:.2f}s) · {c.text}\n")
    if c.id in fell_back:
        lines.append(f"#{c.id} @{c.start:.2f}s: cloned voice failed the quality check, used edge-tts · {c.text}\n")
    if c.id in below_floor:
        lines.append(f"#{c.id} @{c.start:.2f}s: did not fit even shortened, duration factor {c.factor:.2f} "
                     f"below the {floor:.2f} floor · {c.text}\n")
    return lines


def _fit(
    wd: WorkDir, clips: dict[int, Clip], voices: dict[int, Voice], slots: dict[int, float],
    by_id: dict[int, Segment], settings: Settings, engine: str, only: set[int] | None = None,
) -> tuple[set[int], set[int], int, set[int]]:
    """Quality check, shortening and the floor, after the first pass: (fell back to edge-tts,
    still abnormal, how many shortened, below the floor). `only`: just these clips (a retouch)."""
    fixed = hand_edited(wd)
    fell_back: set[int] = set()
    if engine != "edge":
        fell_back = _repair_clones(wd, clips, voices, slots, by_id, settings, only, fixed)
    else:
        # Quality check: regenerate clips with abnormal duration once
        bad_qc = [c for c in suspicious(list(clips.values())) if only is None or c.id in only]
        if bad_qc:
            log.warning(f"Quality check: {len(bad_qc)} clip(s) with abnormal duration, regenerating…")
            segs = [replace(by_id[c.id], text=c.text) for c in bad_qc]
            for clip in _render(wd, segs, slots, settings, voices[bad_qc[0].id], regenerate=True):
                clips[clip.id] = clip
    still_bad = {c.id for c in suspicious(list(clips.values())) if only is None or c.id in only}

    n_short = 0
    if settings.shorten:
        originals = {s.id: s.text for s in load_segments(wd.segments)}
        n_short = _shorten_overflows(wd, clips, originals, slots, by_id, settings, voices, only, fixed)
    below_floor = _below_floor(wd, clips, voices, slots, by_id, settings, only) if native_duration(engine) else set()
    return fell_back, still_bad, n_short, below_floor


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Clip]:
    segments = load_segments(wd.translation)
    cloned = settings.tts == "clone"
    ref = reference.reference(wd) if cloned else None
    engine = resolve_engine(settings, ref)  # also validates --tts and --engine
    seeds = takes(wd) if cloned else {}
    params = _params(settings, segments, engine, ref, seeds)
    ref_f0 = reference.mean_f0(ref) if cloned else None
    choice = None
    if cloned:
        # logged (and kept in tts.json) to later relate the engine choice to the voice pitch
        f0 = f"{ref_f0:.0f} Hz" if ref_f0 else "unknown"
        how = ""
        if settings.engine == "auto":
            how = f" (auto: F0 {'below' if engine == 'indextts' else 'not below'} {AUTO_F0_HZ:.0f} Hz)"
        choice = f"auto (F0 threshold {AUTO_F0_HZ:.0f} Hz)" if settings.engine == "auto" else "manual"
        log.info(f"Cloned voice: engine {engine}{how} ({engine_model(engine)}) · reference mean F0 {f0} · "
                 f"{len(segments)} segments")
    if not force and wd.is_done("tts", params) and wd.tts_index.exists():
        log.info("TTS cached, skipping")
        index = json.loads(wd.tts_index.read_text(encoding="utf-8"))
        if isinstance(index, dict) and index.get("engine_choice") != choice:
            # same clips, chosen another way (e.g. --engine auto landing on the same engine)
            index["engine_choice"] = choice
            wd.tts_index.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        return load_clips(wd)

    started = time.monotonic()
    asyncio.run(_check_voice(settings.voice))  # edge-tts is also the cloned voice's last resort
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    for old in wd.tts_dir.glob("*.wav"):
        old.unlink()

    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, _slots(segments, meta.get("duration")))}
    by_id = {s.id: s for s in segments}
    voice = Voice.clone(settings, ref) if cloned else Voice.edge(settings)
    voices = {s.id: replace(voice, seed=seeds.get(s.id, SEED)) for s in segments}
    if not cloned:
        log.info(f"Voice {settings.voice} ({settings.rate}) · {len(segments)} segments")
    jobs = [(s, voices[s.id]) for s in segments]
    clips = {c.id: c for c in _render_each(wd, jobs, slots, settings, regenerate=force)}
    fell_back, still_bad, n_short, below_floor = _fit(wd, clips, voices, slots, by_id, settings,
                                                      engine if cloned else "edge")

    result = [clips[s.id] for s in segments]
    index = {
        "engine": engine,
        "engine_choice": choice,
        "model": engine_model(engine) if cloned else f"edge-tts {settings.voice}",
        "reference_f0_hz": ref_f0,
        # shown per version in the web: how long the voice took and what it took to fit it
        "stats": {"seconds": round(time.monotonic() - started, 1), "shortened": n_short},
        "clips": [asdict(c) for c in result],
        # the translation each clip was made from: what a retouch compares edits with
        "sources": {str(s.id): s.text for s in segments},
    }
    wd.tts_index.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        for c in result:
            f.writelines(_issue_lines(c, still_bad, fell_back, below_floor, settings.min_factor))

    overflows = [c for c in result if c.overflow > 0]
    sped = sum(1 for c in result if c.tempo > 1.0)
    chars_per_s = sum(len(c.text) for c in result) / sum(c.raw_duration for c in result)
    log.info(
        f"Sped up: {sped} · shortened: {n_short} · do not fit: {len(overflows)}"
        + (f" (max +{max(c.overflow for c in overflows):.2f}s, see overflow.log)" if overflows else "")
    )
    if native_duration(engine):
        fitted = sum(1 for c in result if c.factor < 1.0)
        log.info(f"Fitted with the native duration factor: {fitted} (min {min(c.factor for c in result):.2f}) · "
                 f"below the {settings.min_factor:.2f} floor: {len(below_floor)}")
    if cloned:
        repaired = sum(1 for c in result if c.voice not in (engine, "edge"))
        log.info(f"Cloned clips redone by the quality check: {repaired} · fell back to edge-tts: {len(fell_back)}")
    if fell_back:
        log.warning(f"{len(fell_back)} clip(s) use edge-tts instead of the cloned voice (see overflow.log)")
    if still_bad:
        log.warning(f"{len(still_bad)} clip(s) still have an abnormal duration (see overflow.log)")
    log.info(f"Measured speaking rate: {chars_per_s:.1f} chars/s")
    wd.mark_done("tts", params)
    return result


def retouch(wd: WorkDir, settings: Settings, new_takes: list[int] | tuple[int, ...] = ()) -> list[int]:
    """Speak again only some sentences of the latest dub; returns their ids.

    The sentences whose translation changed since the dub (pending_edits), and
    `new_takes`: the same text with the next seed (another take of a cloned voice).
    Each goes through the same fitting and quality check as a full run, judged
    against the whole video, then tts.json and overflow.log are patched and the
    TTS phase is marked done for the current translation: a later full run finds
    it cached. The engine is the dub's own, whatever `settings` says.
    """
    if not (wd.tts_index.exists() and wd.translation.exists()):
        raise SystemExit("Nothing to retouch: this video has no dub yet")
    index = _index(wd)
    engine = index.get("engine") or "edge"
    cloned = engine != "edge"
    settings = replace(settings, tts="clone" if cloned else "edge", engine=engine if cloned else settings.engine)
    segments = load_segments(wd.translation)
    clips = {c.id: c for c in load_clips(wd)}
    unknown = sorted(set(new_takes) - set(clips))
    if unknown:
        raise SystemExit(f"No segment {unknown[0]} in this dub")
    if not cloned and new_takes:
        raise SystemExit("Another take needs a cloned voice: edge-tts always says a text the same way")

    edits = pending_edits(wd)
    seeds = takes(wd)
    for i in new_takes:
        seeds[i] = seeds.get(i, SEED) + 1
    ids = sorted(edits | set(new_takes))
    if not ids:
        log.info("Nothing to retouch: no edited sentence and no take asked for")
        return []
    log.info(f"Retouch with {engine}: {len(ids)} segment(s) · edited {len(edits)} · new takes {len(new_takes)}")

    started = time.monotonic()
    ref = reference.reference(wd) if cloned else None
    asyncio.run(_check_voice(settings.voice))
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, _slots(segments, meta.get("duration")))}
    translated = {s.id: s for s in segments}
    # an edit speaks the new translation; a take, what the clip said (maybe a shortened version that fit)
    by_id = {i: replace(translated[i], text=translated[i].text if i in edits else clips[i].text) for i in ids}
    base = Voice.clone(settings, ref) if cloned else Voice.edge(settings)
    voices = {i: replace(base, seed=seeds.get(i, SEED)) for i in clips}
    for clip in _render_each(wd, [(by_id[i], voices[i]) for i in ids], slots, settings):
        clips[clip.id] = clip
    fell_back, still_bad, n_short, below_floor = _fit(wd, clips, voices, slots, by_id, settings, engine, set(ids))

    index["clips"] = [asdict(clips[s.id]) for s in segments]
    index["sources"] = {str(s.id): s.text for s in segments}  # every pending edit is spoken now
    index["stats"] = {"seconds": round(time.monotonic() - started, 1), "shortened": n_short, "retouched": ids}
    wd.tts_index.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    # the other clips keep their lines; the mix writes its "delayed" lines again
    kept = []
    if wd.overflow_log.exists():
        for line in wd.overflow_log.read_text(encoding="utf-8").splitlines(keepends=True):
            m = re.match(r"#(\d+) (@|delayed)", line)
            if m and (int(m[1]) in ids or m[2] == "delayed"):
                continue
            kept.append(line)
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        f.writelines(kept)
        for i in ids:
            f.writelines(_issue_lines(clips[i], still_bad, fell_back, below_floor, settings.min_factor))
    (wd.path / "takes.json").write_text(json.dumps({str(k): v for k, v in sorted(seeds.items())}), encoding="utf-8")

    fits = sum(1 for i in ids if clips[i].overflow == 0)
    log.info(f"Retouched {len(ids)} segment(s) in {time.monotonic() - started:.1f}s · fit: {fits} · "
             f"shortened: {n_short} · fell back to edge-tts: {len(fell_back)}")
    wd.mark_done("tts", _params(settings, segments, engine, ref, seeds if cloned else {}))
    return ids
