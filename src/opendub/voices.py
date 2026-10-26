"""The voices of a dub: one voice for every sentence, or each speaker's with several voices.

With one voice, every sentence is cloned from the video's reference (or said by the stock
voice); its last resort is the stock voice of the speaker's gender. With several voices
(--multi-speaker), each speaker is cloned from their own reference with one engine for
all, and a speaker who can't be cloned speaks with the stock voice of their gender.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from . import reference, tts
from .config import Settings
from .log import log
from .models import Segment
from .workdir import WorkDir

# Several voices: the stock edge-tts voice of each gender per variant (a speaker who can't be
# cloned, and every cloned speaker's last resort, speaks with the one of their gender)
STOCK_VOICES = {
    "es-ES": {"male": "es-ES-AlvaroNeural", "female": "es-ES-ElviraNeural"},
    "es-MX": {"male": "es-MX-JorgeNeural", "female": "es-MX-DaliaNeural"},
}


def gender_of(f0: float | None) -> str | None:
    """A speaker's gender from their mean pitch (the same threshold as --engine auto)."""
    return None if f0 is None else ("female" if f0 >= tts.AUTO_F0_HZ else "male")


def stock_voice(base: str, gender: str | None) -> str:
    """The edge-tts voice of `gender` in the variant of `base`: `base` itself if it has that gender."""
    if gender is None:
        return base
    known = {v: g for pair in STOCK_VOICES.values() for g, v in pair.items()}
    if known.get(base) == gender:
        return base
    return STOCK_VOICES.get(base.rsplit("-", 1)[0], STOCK_VOICES["es-ES"])[gender]


def multi_speaker(settings: Settings, segments: list[Segment]) -> bool:
    return settings.multi_speaker and any(s.speaker for s in segments)


def speaker_genders(wd: WorkDir) -> dict[str, str | None]:
    speakers = json.loads(wd.diarization.read_text(encoding="utf-8"))["speakers"] if wd.diarization.exists() else {}
    return {spk: gender_of(info.get("f0_hz")) for spk, info in speakers.items()}


def speaker_voices(
    wd: WorkDir, settings: Settings, segments: list[Segment],
) -> tuple[dict[str, tts.Voice], str, Path | None]:
    """(voice of each speaker, engine, main reference) for a video with several voices.

    Each speaker is cloned from their own reference (reference.speaker_reference)
    with one engine for all, the one --engine resolves (with auto, CosyVoice when
    more than one person speaks); a speaker without enough clean speech, and everyone with
    --tts edge, speaks with the stock voice of their gender.
    """
    cloned = settings.tts == "clone"
    speakers = sorted({s.speaker for s in segments if s.speaker})
    genders = speaker_genders(wd)
    refs = {spk: reference.speaker_reference(wd, spk) for spk in speakers} if cloned else {}
    main_ref = next((refs[spk] for spk in speakers if refs.get(spk)), None)
    if cloned and main_ref is None:  # nobody has a clean stretch: the usual reference
        main_ref = reference.reference(wd)
    engine = tts.resolve_engine(settings, main_ref, several=len(speakers) > 1)
    voices = {}
    for spk in speakers:
        gender = genders.get(spk)
        stock = stock_voice(settings.voice, gender)
        if cloned and refs.get(spk):
            voices[spk] = tts.Voice(engine, settings.voice, settings.rate, ref=refs[spk], label=engine,
                                    stock=stock, gender=gender)
        else:
            voices[spk] = tts.Voice("edge", stock, settings.rate, gender=gender)
    return voices, engine, main_ref


def segment_voices(
    wd: WorkDir, settings: Settings, segments: list[Segment], seeds: dict[int, int],
) -> tuple[dict[int, tts.Voice], str, Path | None, dict[str, tts.Voice]]:
    """(voice of each segment, engine, main reference, voice of each speaker — empty with one voice)."""
    voices, engine, ref, by_speaker = _segment_voices(wd, settings, segments, seeds)
    if settings.ref_per_sentence and settings.tts == "clone":
        voices = sentence_voices(wd, segments, voices)
    return voices, engine, ref, by_speaker


def sentence_voices(wd: WorkDir, segments: list[Segment], voices: dict[int, tts.Voice]) -> dict[int, tts.Voice]:
    """--ref-per-sentence (T-30, experimental): each cloned sentence long and clean enough is
    cloned from its own original voice, at its speaker's pace; the rest keep the speaker's."""
    turns = json.loads(wd.diarization.read_text(encoding="utf-8"))["turns"] if wd.diarization.exists() else None
    out = dict(voices)
    own = 0
    for seg in segments:
        v = voices[seg.id]
        if v.engine == "edge" or v.ref is None:
            continue
        path = reference.sentence_reference(wd, seg, tts.SENTENCE_REF_MIN, turns if seg.speaker else None)
        if path:
            out[seg.id] = replace(v, ref=path, pace_ref=v.ref, label=f"{v.engine} (own voice)")
            own += 1
    log.info(f"Reference per sentence: {own} of {len(segments)} sentences cloned from their own voice")
    return out


def _segment_voices(
    wd: WorkDir, settings: Settings, segments: list[Segment], seeds: dict[int, int],
) -> tuple[dict[int, tts.Voice], str, Path | None, dict[str, tts.Voice]]:
    if multi_speaker(settings, segments):
        by_speaker, engine, ref = speaker_voices(wd, settings, segments)
        main = next(iter(by_speaker.values()))
        voices = {s.id: replace(by_speaker.get(s.speaker or "", main), seed=seeds.get(s.id, tts.SEED)) for s in segments}
        return voices, engine, ref, by_speaker
    cloned = settings.tts == "clone"
    ref = reference.reference(wd) if cloned else None
    engine = tts.resolve_engine(settings, ref)  # also validates --tts and --engine
    base = tts.Voice.edge(settings)
    if ref is not None:
        # the last resort speaks with a stock voice of the speaker's gender, not --voice's: a woman's
        # clip said by Álvaro in the middle of her cloned voice. Only the fallback: the translation
        # prompts don't get a gender with one voice
        base = replace(tts.Voice.clone(settings, ref),
                       stock=stock_voice(settings.voice, gender_of(reference.mean_f0(ref))))
    return {s.id: replace(base, seed=seeds.get(s.id, tts.SEED)) for s in segments}, engine, ref, {}


def speaker_paces(wd: WorkDir, settings: Settings, segments: list[Segment]) -> dict[str, tts.Pace]:
    """The pace of each speaker's voice (several voices), calibrating whatever isn't yet."""
    by_speaker, _, _ = speaker_voices(wd, settings, segments)
    return {spk: tts.cloned_speaking_rate(settings, v) if v.engine != "edge"
            else tts.Pace(tts.speaking_rate(settings.work_root, v.name, v.rate)) for spk, v in by_speaker.items()}


def describe(by_speaker: dict[str, tts.Voice]) -> dict[str, dict]:
    """How each speaker speaks, for tts.json and the web page."""
    return {spk: {"engine": v.engine, "voice": v.name if v.engine == "edge" else None,
                  "reference": v.ref.name if v.ref else None, "gender": v.gender, "stock": v.stock}
            for spk, v in by_speaker.items()}
