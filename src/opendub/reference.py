"""The original speaker's reference recording for voice cloning, and its pitch.

The reference is cut from the separated vocals: the 10–15 s stretch with the
fewest pauses. Choosing it by quality (8–12 s with the least music under it)
was tried for the female voice's IndexTTS tremor and dropped: it lowered
similarity to the original voice in real dubs without a tremor change that the
ear or the 3–9 Hz measure could confirm (docs/v2-plan.md).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import media
from .media import ffmpeg
from .models import Segment, load_segments
from .workdir import WorkDir

SAMPLE_RATE = 24000
REF_MIN, REF_MAX = 10.0, 15.0  # seconds of reference audio
REF_SPEAKER_MIN = 6.0  # several voices: a speaker with less clean speech is not cloned (stock voice)


def _window(segments: list[Segment]) -> tuple[tuple[float, float], tuple[bool, float]] | None:
    """((start, end), key) of the best window of consecutive segments, or None."""
    best: tuple[float, float] | None = None
    best_key: tuple[bool, float] | None = None
    for i, first in enumerate(segments):
        for j in range(i, len(segments)):
            span = segments[j].end - first.start
            if span > REF_MAX:
                break
            speech = sum(s.duration for s in segments[i : j + 1])
            key = (span >= REF_MIN, speech / span if span >= REF_MIN else span)
            if best_key is None or key > best_key:
                best, best_key = (first.start, segments[j].end), key
    return (best, best_key) if best and best_key else None


def pick_reference(segments: list[Segment]) -> tuple[float, float]:
    """(start, end) of the consecutive segments that make the best reference.

    Prefers windows of REF_MIN–REF_MAX seconds with the most speech (fewest
    pauses); without any, the longest window under REF_MAX; if every segment is
    longer than that, the first REF_MAX seconds of the first one.
    """
    found = _window(segments)
    best = found[0] if found else None
    if best is None:
        if not segments:
            raise SystemExit("There are no segments to take a voice reference from")
        return segments[0].start, segments[0].start + REF_MAX
    return best


def _load(path: Path, sr: int = 16000) -> np.ndarray:
    raw = media.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def reference(wd: WorkDir) -> Path:
    """Cut the reference clip of the original speaker from the separated vocals."""
    if not wd.vocals.exists():
        raise SystemExit("Voice cloning needs the separated vocals: run `separate` first (or use `dub`)")
    start, end = pick_reference(load_segments(wd.segments))
    path = wd.path / "clone_ref.wav"
    ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(wd.vocals),
           "-ac", "1", "-ar", str(SAMPLE_RATE), str(path))
    return path


def speaker_reference(wd: WorkDir, speaker: str) -> Path | None:
    """The reference clip of one speaker (several voices), or None without enough clean speech.

    Windows are taken only inside runs of that speaker's consecutive sentences,
    so no one else's voice gets into it; under REF_SPEAKER_MIN seconds the
    speaker is not cloned.
    """
    if not wd.vocals.exists():
        raise SystemExit("Voice cloning needs the separated vocals: run `separate` first (or use `dub`)")
    runs: list[list[Segment]] = []
    for seg in load_segments(wd.segments):
        if seg.speaker == speaker:
            if runs and runs[-1][-1].id == seg.id - 1:
                runs[-1].append(seg)
            else:
                runs.append([seg])
    windows = [w for run in runs if (w := _window(run))]
    if not windows:
        return None
    (start, end), _ = max(windows, key=lambda w: w[1])
    if end - start < REF_SPEAKER_MIN:
        return None
    path = wd.path / f"clone_ref_{speaker}.wav"
    ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(wd.vocals),
           "-ac", "1", "-ar", str(SAMPLE_RATE), str(path))
    return path


def sentence_reference(wd: WorkDir, seg: Segment, min_s: float, turns: list | None = None) -> Path | None:
    """The sentence's own voice, cut from the separated vocals, as its reference (T-30), or None.

    None when it lasts under `min_s` (too little to clone from) or, with several voices,
    when someone else speaks over more than OVERLAP_S of it.
    """
    if seg.duration < min_s:
        return None
    if turns:
        others = sum(max(0.0, min(end, seg.end) - max(start, seg.start))
                     for start, end, speaker in turns if speaker != seg.speaker)
        if others > OVERLAP_S:
            return None
    folder = wd.path / "sentence_refs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{seg.id:04d}.wav"
    ffmpeg("-ss", f"{seg.start:.3f}", "-to", f"{seg.end:.3f}", "-i", str(wd.vocals),
           "-ac", "1", "-ar", str(SAMPLE_RATE), str(path))
    return path


OVERLAP_S = 0.3  # seconds of another speaker a sentence's own reference tolerates


def mean_f0(path: Path) -> float | None:
    """Mean fundamental frequency (Hz) of the voiced frames of a recording, or None.

    A plain autocorrelation pitch tracker (40 ms frames, 60–400 Hz): enough to
    tell low from high voices, which is what it is logged for.
    """
    sr = 16000
    audio = _load(path, sr)
    size, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = sr // 400, sr // 60  # lag range for 400–60 Hz
    frames = [audio[i : i + size] for i in range(0, len(audio) - size, hop)]
    if not frames:
        return None
    loudest = max(float(np.sqrt(np.mean(f**2))) for f in frames)
    pitches = []
    for f in frames:
        if np.sqrt(np.mean(f**2)) < 0.1 * loudest:
            continue  # silence or breath
        f = f - f.mean()
        ac = np.correlate(f, f, mode="full")[size - 1 :]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.5:  # clearly periodic: voiced
            pitches.append(sr / lag)
    if len(pitches) < 10:
        return None
    median = float(np.median(pitches))
    kept = [p for p in pitches if 0.6 * median < p < 1.6 * median]  # drop octave errors
    return round(float(np.mean(kept)), 1)
