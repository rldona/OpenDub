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
6. A clip that finishes well before its sentence did in the original is slowed down,
   to min_tempo at most, so a fast voice does not leave silences mid-conversation;
   only as far as it can without pushing the next clip, where the mix will place it.

Steps 4–5 live in repair.py, the voice of each sentence (one, or each speaker's) in
voices.py, and speaking again only some sentences of a dub in retouch.py.
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

from . import reference, repair
from . import retouch as retouch_mod
from . import voices as voices_mod
from .config import Settings
from .log import Progress, console, log
from .media import ffmpeg
from .models import Segment, load_segments
from .spoken import spell_numbers
from .workdir import WorkDir, write_text_atomic

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
SENTENCE_REF_MIN = 3.0  # --ref-per-sentence: shorter sentences are cloned from the speaker's reference


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
    stock: str | None = None  # several voices: the stock voice of the speaker's gender (last resort)
    gender: str | None = None  # several voices: "female" | "male", from the speaker's pitch
    # --ref-per-sentence: the speaker's reference while `ref` is the sentence's own voice; its
    # calibrated pace is the clip's, and it is the first fallback when the clip fails the check
    pace_ref: Path | None = None

    def cloned_ref(self) -> Path:
        """The reference of a cloned voice: every one has it (only edge-tts voices don't)."""
        if self.ref is None:
            raise ValueError(f"A {self.engine} voice without a reference")
        return self.ref

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


def choose_tempo(duration: float, slot: float, max_tempo: float) -> float:
    """atempo factor: speed up if it does not fit (slowing down is fill_gaps', once all clips are known)."""
    if duration > slot:
        return min(duration / slot, max_tempo)
    return 1.0


FILL_BELOW = 0.95  # a clip filling more of its room than this is left as it is


def slow_downs(clips: list[Clip], ends: dict[int, float], min_tempo: float,
               only: set[int] | None = None) -> dict[int, float]:
    """Tempo (<1) for the clips that end well before their sentence did in the original (`ends`).

    It walks the clips as mix.place does, so a clip pushed by the one before has less
    room, and a slowed clip never ends past the next one's timestamp: slowing down
    must not eat the slack that absorbs a delay. Sped-up and already slowed clips are
    left as they are, and with `only` (a retouch) so is every other clip.
    """
    from .mix import MIN_GAP  # lazy: mix imports this module

    out: dict[int, float] = {}
    if min_tempo >= 1.0:
        return out
    ordered = sorted(clips, key=lambda c: c.start)
    cursor = 0.0
    for i, c in enumerate(ordered):
        start = c.start if c.start >= cursor else cursor + MIN_GAP
        length = c.duration
        nxt = ordered[i + 1].start - MIN_GAP if i + 1 < len(ordered) else float("inf")
        room = min(ends.get(c.id, c.start + c.duration), nxt) - start
        if c.tempo == 1.0 and (only is None or c.id in only) and length < FILL_BELOW * room:
            out[c.id] = max(length / room, min_tempo)
            length /= out[c.id]
        cursor = start + length
    return out


def fill_gaps(wd: WorkDir, clips: dict[int, Clip], segments: list[Segment], min_tempo: float,
              only: set[int] | None = None) -> int:
    """Slow down the clips slow_downs picks (step 6), in place; returns how many."""
    tempos = slow_downs(list(clips.values()), {s.id: s.end for s in segments}, min_tempo, only)
    for i, tempo in tempos.items():
        c = clips[i]
        _slow(wd.path / c.file, tempo)
        clips[i] = replace(c, tempo=round(tempo, 3), duration=round(c.duration / tempo, 3))
    return len(tempos)


def _slow(final: Path, tempo: float) -> None:
    """Play a clip at `tempo`, in place."""
    slowed = final.with_suffix(".slow.wav")
    ffmpeg("-i", str(final), "-af", f"atempo={tempo:.4f}", str(slowed))
    slowed.replace(final)


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
    def natural(c: Clip) -> float:
        return spoken_len(c.text) * c.factor / c.raw_duration

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
        raw = f"{engine_model(voice.engine)}\n{clone.file_hash(voice.cloned_ref())}\n{voice.seed}\nspoken-v1\n{text}"
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
        try:
            asyncio.run(_synthesize_all(group, name, rate))
        except RuntimeError as e:  # after its retries: say why it may have failed
            raise SystemExit(f"{e}. {NETWORK_HINT}")
    if not cloned:
        return
    from . import clone, cosyvoice, indextts

    # One GPU model: clips go one after another
    with Progress(
        "[progress.description]{task.description}", BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Cloning voice", total=len(cloned))
        # Chatterbox clips go to its process pool, several at a time (clone.synthesize_batch), per variant
        for engine, variant in CHATTERBOX.items():
            batch = [(spell_numbers(text), voice.cloned_ref(), voice.seed, path) for text, path, voice in cloned
                     if voice.engine == engine]
            if batch:
                clone.synthesize_batch(batch, settings.work_root / "chatterbox.log", lambda: progress.advance(task),
                                       variant)
        for text, path, voice in cloned:
            said = spell_numbers(text)  # cloned voices misread figures and "2x2"
            if voice.engine in CHATTERBOX:
                continue
            if voice.engine == "indextts":
                indextts.synthesize(settings.indextts_dir, settings.work_root / "indextts.log",
                                    said, voice.cloned_ref(), path, voice.factor, voice.seed)
            elif voice.engine == "cosyvoice":
                cosyvoice.synthesize(settings.cosyvoice_dir, settings.work_root / "cosyvoice.log",
                                     said, voice.cloned_ref(), path, voice.factor, voice.seed)
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


NETWORK_HINT = "Is there an internet connection?"
CHECK_VOICE_TIMEOUT_S = 20


async def _check_voice(voice: str) -> None:
    import edge_tts

    try:
        listed = await asyncio.wait_for(edge_tts.list_voices(), CHECK_VOICE_TIMEOUT_S)
    except Exception as e:  # aiohttp's network errors, a timeout: one clear message, no endless retries
        raise SystemExit(f"Can't reach edge-tts (Microsoft's voices) to check the voice {voice}: "
                         f"{type(e).__name__}. {NETWORK_HINT} It is also the cloned voice's last resort.")
    voices = {v["ShortName"] for v in listed}
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
    write_text_atomic(cache, json.dumps(rates, indent=1))
    log.info(f"Calibrated rate for {voice} ({rate}): {rates[key]} chars/s")
    return rates[key]


def cloned_speaking_rate(settings: Settings, voice: Voice) -> Pace:
    """Pace of a cloned voice (per-clip overhead and chars/s), cached like speaking_rate.

    Engines with a native duration control are measured at their
    CALIBRATION_FACTOR, the pace their clips are planned around (IndexTTS 0.85,
    CosyVoice 1.0); Chatterbox at its only pace.
    """
    factor = calibration_factor(voice.engine)
    if voice.pace_ref:  # a sentence's own voice speaks at its speaker's pace: never calibrated alone
        voice = replace(voice, ref=voice.pace_ref, pace_ref=None)
    cache = settings.work_root / "voice_rates.json"
    rates = json.loads(cache.read_text()) if cache.exists() else {}
    key = cloned_rate_key(voice.engine, voice.cloned_ref())
    if key not in rates:
        samples = _calibrate(settings, replace(voice, factor=factor, seed=SEED), CALIBRATION_SENTENCES + CALIBRATION_EXTRA)
        rates[key] = asdict(fit_pace(samples))
        write_text_atomic(cache, json.dumps(rates, indent=1))
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
    if settings.tts == "clone":  # Voice.clone resolves the engine (auto, one voice: Chatterbox)
        return cloned_speaking_rate(settings, Voice.clone(settings, reference.reference(wd)))
    resolve_engine(settings)  # validates --tts
    return Pace(speaking_rate(settings.work_root, settings.voice, settings.rate))


# --engine; Settings.engine defaults to auto. chatterbox-es (the es-ES finetune) is a CLI-only
# variant for the blind listening, not offered on the web page
CLONE_ENGINES = ("chatterbox", "indextts", "cosyvoice", "chatterbox-es")
CHATTERBOX = {"chatterbox": "v3", "chatterbox-es": "es-es"}  # engine → clone variant
# Engines that scale a clip's duration themselves (a duration factor): their clips are
# fitted to the slot natively, down to --min-factor, before shortening and atempo
NATIVE_DURATION = ("indextts", "cosyvoice")


AUTO_F0_HZ = 165.0  # a speaker's gender: references below it are a man's (voices.gender_of)


def resolve_engine(settings: Settings, ref: Path | None = None, several: bool = False) -> str:
    """The engine that speaks: edge for --tts edge, the --engine choice for --tts clone.

    `auto`, the default, picks by the dub: CosyVoice when several people speak
    (`several`), Chatterbox for one voice. Heard blind (docs/audit/03-competencia.md
    section 12), CosyVoice won the two-host podcast clearly (4.2 against 3.0) and
    Chatterbox narration by a little (4.0 against 3.5). Without CosyVoice installed,
    Chatterbox. `ref` is no longer needed; kept for the callers that pass it.
    """
    if settings.tts not in ("edge", "clone"):
        raise SystemExit(f"--tts must be edge or clone (not {settings.tts!r})")
    if settings.tts == "edge":
        return "edge"
    if settings.engine not in (*CLONE_ENGINES, "auto"):
        raise SystemExit(f"--engine must be {', '.join(CLONE_ENGINES)} or auto (not {settings.engine!r})")
    if settings.engine != "auto":
        return settings.engine
    from . import cosyvoice

    return "cosyvoice" if several and cosyvoice.installed(settings.cosyvoice_dir) else "chatterbox"


def native_duration(engine: str) -> bool:
    return engine in NATIVE_DURATION


def _engine_module(engine: str):
    from . import clone, cosyvoice, indextts

    return {"chatterbox": clone, "chatterbox-es": clone, "indextts": indextts, "cosyvoice": cosyvoice}[engine]


def calibration_factor(engine: str) -> float:
    return _engine_module(engine).CALIBRATION_FACTOR if native_duration(engine) else 1.0


def min_factor(engine: str) -> float:
    """The lowest duration factor an engine is asked for (below --min-factor, a last resort)."""
    return _engine_module(engine).MIN_FACTOR


def engine_model(engine: str) -> str:
    if engine in CHATTERBOX:
        from . import clone

        return clone.VARIANTS[CHATTERBOX[engine]]
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
    tempo = choose_tempo(raw_dur, slot, settings.max_tempo)
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
    (repair.shorten_overflows), and only then compressed further (repair.below_floor).
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


def clips_exist(wd: WorkDir) -> bool:
    """Whether the latest dub's voice clips are all on disk (storage.py can delete them)."""
    if not wd.tts_index.exists():
        return False
    return all((wd.path / c.file).exists() for c in load_clips(wd))


def _index(wd: WorkDir) -> dict:
    data = json.loads(wd.tts_index.read_text(encoding="utf-8"))
    return {"engine": None, "clips": data} if isinstance(data, list) else data


def _params(settings: Settings, segments: list[Segment], engine: str, ref: Path | None,
            seeds: dict[int, int], by_speaker: dict[str, Voice] | None = None) -> dict:
    """What a TTS run depends on: the cache key of the phase."""
    from . import clone

    params = {
        "voice": settings.voice,
        "rate": check_rate(settings.rate),
        "min_tempo": settings.min_tempo,
        "slowing": "placed",  # tts.fill_gaps: slowed where the mix places each clip, not clip by clip
        "max_tempo": settings.max_tempo,
        "shorten": settings.translator() if settings.shorten else None,
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
    if settings.ref_per_sentence and ref is not None:
        params["ref_per_sentence"] = SENTENCE_REF_MIN
    if seeds:  # only then: dubs without takes keep their cache
        params["takes"] = sorted(seeds.items())
    if by_speaker:  # several voices: whose each sentence is, and how each one speaks
        from . import clone

        params["speakers"] = [(s.id, s.speaker) for s in segments]
        params["speaker_voices"] = {spk: [v.engine, clone.file_hash(v.ref) if v.ref else v.name]
                                    for spk, v in sorted(by_speaker.items())}
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


def run(wd: WorkDir, settings: Settings, force: bool = False) -> list[Clip]:
    segments = load_segments(wd.translation)
    cloned = settings.tts == "clone"
    seeds = retouch_mod.takes(wd) if cloned else {}
    voices, engine, ref, by_speaker = voices_mod.segment_voices(wd, settings, segments, seeds)
    params = _params(settings, segments, engine, ref, seeds, by_speaker)
    ref_f0 = reference.mean_f0(ref) if ref is not None else None
    choice = None
    if cloned:
        # logged (and kept in tts.json) to later relate the engine choice to the voices
        f0 = f"{ref_f0:.0f} Hz" if ref_f0 else "unknown"
        how = ""
        if settings.engine == "auto":
            how = f" (auto: {'several voices' if len(by_speaker) > 1 else 'one voice'})"
        choice = "auto (CosyVoice with several voices, Chatterbox with one)" if settings.engine == "auto" else "manual"
        log.info(f"Cloned voice: engine {engine}{how} ({engine_model(engine)}) · reference mean F0 {f0} · "
                 f"{len(segments)} segments")
    for spk, v in by_speaker.items():
        said = sum(1 for seg in segments if seg.speaker == spk)
        how = f"cloned with {v.engine}" if v.engine != "edge" else f"stock voice {v.name}"
        log.info(f"Speaker {spk} ({v.gender or 'gender unknown'}): {how} · {said} segments")
    if not force and wd.is_done("tts", params) and clips_exist(wd):  # deleted to save space: speak them again
        log.info("TTS cached, skipping")
        index = json.loads(wd.tts_index.read_text(encoding="utf-8"))
        if isinstance(index, dict) and index.get("engine_choice") != choice:
            # same clips, chosen another way (e.g. --engine auto landing on the same engine)
            index["engine_choice"] = choice
            write_text_atomic(wd.tts_index, json.dumps(index, ensure_ascii=False, indent=1))
        return load_clips(wd)

    started = time.monotonic()
    asyncio.run(_check_voice(settings.voice))  # edge-tts is also the cloned voice's last resort
    (wd.tts_dir / "raw").mkdir(parents=True, exist_ok=True)
    for old in wd.tts_dir.glob("*.wav"):
        old.unlink()

    meta = json.loads(wd.meta.read_text(encoding="utf-8"))
    slots = {s.id: slot for s, slot in zip(segments, _slots(segments, meta.get("duration")))}
    by_id = {s.id: s for s in segments}
    if not cloned and not by_speaker:
        log.info(f"Voice {settings.voice} ({settings.rate}) · {len(segments)} segments")
    jobs = [(s, voices[s.id]) for s in segments]
    clips = {c.id: c for c in _render_each(wd, jobs, slots, settings, regenerate=force)}
    fell_back, still_bad, n_short, below_floor = repair.fit(repair.Fitting(wd, clips, voices, slots, by_id, settings),
                                                            engine if cloned else "edge")
    slowed = fill_gaps(wd, clips, segments, settings.min_tempo)

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
    if by_speaker:  # several voices: who each clip was spoken as, and how each speaker speaks
        index["speakers"] = {str(s.id): s.speaker for s in segments}
        index["speaker_voices"] = voices_mod.describe(by_speaker)
    write_text_atomic(wd.tts_index, json.dumps(index, ensure_ascii=False, indent=1))
    with wd.overflow_log.open("w", encoding="utf-8") as f:
        for c in result:
            f.writelines(_issue_lines(c, still_bad, fell_back, below_floor, settings.min_factor))

    overflows = [c for c in result if c.overflow > 0]
    sped = sum(1 for c in result if c.tempo > 1.0)
    chars_per_s = sum(len(c.text) for c in result) / sum(c.raw_duration for c in result)
    log.info(
        f"Sped up: {sped} · slowed down: {slowed} · shortened: {n_short} · do not fit: {len(overflows)}"
        + (f" (max +{max(c.overflow for c in overflows):.2f}s, see overflow.log)" if overflows else "")
    )
    if native_duration(engine):
        fitted = sum(1 for c in result if c.factor < 1.0)
        log.info(f"Fitted with the native duration factor: {fitted} (min {min(c.factor for c in result):.2f}) · "
                 f"below the {settings.min_factor:.2f} floor: {len(below_floor)}")
    if cloned:
        own = sum(1 for c in result if c.voice.endswith("(own voice)"))  # --ref-per-sentence, not a repair
        repaired = sum(1 for c in result if c.voice not in (engine, "edge") and not c.voice.endswith("(own voice)"))
        log.info(f"Cloned clips redone by the quality check: {repaired} · fell back to edge-tts: {len(fell_back)}"
                 + (f" · spoken with their own voice: {own}" if settings.ref_per_sentence else ""))
    if fell_back:
        log.warning(f"{len(fell_back)} clip(s) use edge-tts instead of the cloned voice (see overflow.log)")
    if still_bad:
        log.warning(f"{len(still_bad)} clip(s) still have an abnormal duration (see overflow.log)")
    log.info(f"Measured speaking rate: {chars_per_s:.1f} chars/s")
    wd.mark_done("tts", params)
    return result


