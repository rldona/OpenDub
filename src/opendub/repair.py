"""After the voice's first pass: the quality check and its repairs, shortening and the floor.

Every step works on a Fitting: the clips so far (replaced in place as they are spoken
again), each sentence's voice and slot, the sentences as they are to be said, and
which clips the step may touch. A full run fits every clip; a retouch only its own,
judged against the whole video.

1. Quality check (`repair_clones`): a cloned clip that whisper can't understand or
   whose speed is abnormal goes down a fallback chain that keeps the voice as long
   as possible: another seed → a shorter sentence → the fixed reference
   (--clone-ref) → the stock voice. Stock-voice dubs regenerate abnormal clips once.
2. Shortening (`shorten_overflows`): Claude rewrites the sentences that don't fit,
   up to tts.SHORTEN_ROUNDS rounds; hand-edited sentences are never rewritten.
3. The floor (`below_floor`): native-duration clips that don't fit even shortened
   are compressed below --min-factor, down to the engine's own minimum.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import retouch, style, tts
from .config import Settings
from .log import log
from .models import Segment, load_segments
from .workdir import WorkDir


@dataclass
class Fitting:
    wd: WorkDir
    clips: dict[int, tts.Clip]  # every clip of the dub, replaced in place as they are spoken again
    voices: dict[int, tts.Voice]  # each sentence's voice; a repair that changes it updates it
    slots: dict[int, float]
    by_id: dict[int, Segment]  # the sentences to speak, with the text to say
    settings: Settings
    only: set[int] | None = None  # a retouch: just these clips
    fixed: set[int] = field(default_factory=set)  # hand-edited texts, never rewritten shorter

    def touched(self, clip_id: int) -> bool:
        return self.only is None or clip_id in self.only

    def speak(self, jobs: list[tuple[Segment, tts.Voice]], each: bool = True, regenerate: bool = False) -> None:
        """Speak these sentences again and put their clips in place (`each`: fitted to their slot)."""
        render = tts._render_each if each else tts._render_jobs
        for clip in render(self.wd, jobs, self.slots, self.settings, regenerate=regenerate):
            self.clips[clip.id] = clip


def clip_overhead(clip: tts.Clip, voice: tts.Voice, settings: Settings) -> float:
    """Seconds of this clip that don't depend on its length (cloned voices' calibrated overhead)."""
    if voice.engine == "edge":
        return 0.0
    overhead = tts.cloned_speaking_rate(settings, voice).overhead
    return overhead * clip.factor / tts.calibration_factor(voice.engine)


def needs_shortening(clip: tts.Clip, voice: tts.Voice) -> bool:
    """Native duration: it doesn't fit at --min-factor, before atempo. Others: not even after atempo."""
    if tts.native_duration(voice.engine):
        return clip.raw_duration - clip.slot > tts.OVERFLOW_TOLERANCE
    return clip.overflow > tts.OVERFLOW_TOLERANCE


def below_floor(f: Fitting) -> set[int]:
    """Last step for native-duration clips that don't fit even shortened: compress below --min-factor.

    Down to the engine's MIN_FACTOR; atempo covers whatever is still left.
    Returns the ids compressed this way (they go to overflow.log).
    """
    from . import engines

    jobs = []
    for c in f.clips.values():
        if not f.touched(c.id):
            continue
        v = f.voices[c.id]
        if tts.native_duration(v.engine) and c.raw_duration > c.slot:
            factor = engines.fit_factor(c.raw_duration, c.slot, c.factor, floor=tts.min_factor(v.engine))
            if factor < c.factor - 0.01:
                jobs.append((replace(f.by_id[c.id], text=c.text), replace(v, factor=factor)))
    f.speak(jobs, each=False)
    # a last correction that stays above the floor is routine; only the ones below it are reported
    return {seg.id for seg, voice in jobs if voice.factor < f.settings.min_factor}


def shorten_overflows(f: Fitting, originals: dict[int, str]) -> int:
    """Re-translate and re-synthesize clips that do not fit. Return how many were shortened.

    Hand-edited texts (f.fixed) are never rewritten: they are compressed (duration
    factor, atempo) as far as that goes instead.
    """
    from . import translate  # lazy import: translate also imports this module

    settings = f.settings
    shortened: set[int] = set()
    for round_ in range(1, tts.SHORTEN_ROUNDS + 1):
        bad = [c for c in f.clips.values() if f.touched(c.id) and c.id not in f.fixed
               and needs_shortening(c, f.voices[c.id]) and not tts.tiny(c.text)]
        if not bad:
            break
        log.info(f"Shortening round {round_}: {len(bad)} sentence(s) do not fit, asking for shorter versions…")
        # native-duration engines aim to fit without atempo: the target leaves it out
        items = [(c.id, originals[c.id], c.text,
                  tts.shorten_target(c.text, c, 1.0 if tts.native_duration(f.voices[c.id].engine)
                                     else settings.max_tempo, clip_overhead(c, f.voices[c.id], settings)))
                 for c in bad]
        new_texts = translate.shorten(items, settings.voice, settings,
                                      style.load(settings.work_root, f.wd.path, settings.style_file),
                                      {c.id: f.voices[c.id].gender for c in bad})
        f.speak([(replace(f.by_id[i], text=t), f.voices[i]) for i, t in new_texts.items()])
        shortened.update(new_texts)
    return len(shortened)


def clone_failures(wd: WorkDir, ids: set[int], clips: dict[int, tts.Clip], settings: Settings) -> set[int]:
    """Cloned clips among `ids` with an abnormal duration or that whisper can't understand."""
    from . import clone

    bad = {c.id for c in tts.suspicious(list(clips.values())) if c.id in ids}
    rest = [(i, wd.path / clips[i].file, clips[i].text) for i in sorted(ids - bad) if not tts.tiny(clips[i].text)]
    return bad | (clone.unintelligible(rest, settings.whisper_model) if rest else set())


def repair_clones(f: Fitting) -> set[int]:
    """Redo the cloned clips that fail the quality check without switching voices mid-video.

    Fallback chain, each step only for the clips the previous one could not fix:
    (--ref-per-sentence: the speaker's reference →) another seed → a sentence
    shortened by Claude → the fixed reference (--clone-ref) → edge-tts. Returns the
    ids that ended up with edge-tts.

    A retouch checks just its clips (f.only), judged against the whole video's
    speed; hand-edited texts (f.fixed) skip the shorter-sentence step.
    """
    from . import translate  # lazy import: translate also imports this module

    settings, voices, clips = f.settings, f.voices, f.clips
    candidates = {i for i in (set(clips) if f.only is None else f.only) if voices[i].engine != "edge"}
    bad = clone_failures(f.wd, candidates, clips, settings) if candidates else set()  # stock voices aren't checked
    steps = ["the speaker's reference", "another seed", "a shorter sentence", "the fixed reference", "edge-tts"]
    for step in steps:
        if not bad:
            return set()
        if step == "a shorter sentence" and not settings.shorten:
            continue
        if step == "the fixed reference" and not settings.clone_ref:
            continue
        if step == "the speaker's reference" and not any(voices[i].pace_ref for i in bad):
            continue
        log.warning(f"Quality check: {len(bad)} cloned clip(s) failed, retrying with {step}…")
        texts = {i: clips[i].text for i in bad}
        if step == "the speaker's reference":  # a sentence's own voice failed: back to the speaker's
            new_voices = {i: replace(voices[i], ref=voices[i].pace_ref, pace_ref=None, label=voices[i].engine)
                          for i in bad if voices[i].pace_ref}
        elif step == "another seed":
            new_voices = {i: replace(voices[i], seed=voices[i].seed + 1, label=f"{voices[i].engine} (seed+1)")
                          for i in bad}
        elif step == "a shorter sentence":
            originals = {s.id: s.text for s in load_segments(f.wd.segments)}
            items = [(i, originals[i], texts[i], max(int(len(texts[i]) * 0.85), 1)) for i in sorted(bad)
                     if not tts.tiny(texts[i]) and i not in f.fixed]
            if not items:
                continue
            st = style.load(settings.work_root, f.wd.path, settings.style_file)
            texts = {**texts, **translate.shorten(items, settings.voice, settings, st,
                                                  {i: voices[i].gender for i, *_ in items})}
            new_voices = {i: replace(voices[i], label=f"{voices[i].engine} (shortened)") for i, *_ in items}
        elif step == "the fixed reference":
            new_voices = {i: replace(voices[i], ref=settings.clone_ref, seed=tts.SEED,
                                     label=f"{voices[i].engine} (fixed reference)") for i in bad}
        else:
            new_voices = {i: tts.Voice("edge", voices[i].stock or settings.voice, settings.rate,
                                       gender=voices[i].gender) for i in bad}
        redo = set(new_voices)  # a tiny or hand-edited text skips the shorter-sentence step as it is
        f.speak([(replace(f.by_id[i], text=texts[i]), new_voices[i]) for i in sorted(redo)])
        voices.update(new_voices)
        if step == "edge-tts":
            return bad
        bad = clone_failures(f.wd, redo, clips, settings) | (bad - redo)
    return set()


def fit(f: Fitting, engine: str) -> tuple[set[int], set[int], int, set[int]]:
    """Quality check, shortening and the floor, after the first pass: (fell back to edge-tts,
    still abnormal, how many shortened, below the floor)."""
    f.fixed = retouch.hand_edited(f.wd)
    fell_back: set[int] = set()
    if engine != "edge":
        fell_back = repair_clones(f)
    else:
        # Quality check: regenerate clips with abnormal duration once
        bad_qc = [c for c in tts.suspicious(list(f.clips.values())) if f.touched(c.id)]
        if bad_qc:
            log.warning(f"Quality check: {len(bad_qc)} clip(s) with abnormal duration, regenerating…")
            # each with its own voice
            f.speak([(replace(f.by_id[c.id], text=c.text), f.voices[c.id]) for c in bad_qc], each=False,
                    regenerate=True)
    still_bad = {c.id for c in tts.suspicious(list(f.clips.values())) if f.touched(c.id)}

    n_short = 0
    if f.settings.shorten:
        originals = {s.id: s.text for s in load_segments(f.wd.segments)}
        n_short = shorten_overflows(f, originals)
    floor = below_floor(f) if tts.native_duration(engine) else set()
    return fell_back, still_bad, n_short, floor
