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


def pick_reference(segments: list[Segment]) -> tuple[float, float]:
    """(start, end) of the consecutive segments that make the best reference.

    Prefers windows of REF_MIN–REF_MAX seconds with the most speech (fewest
    pauses); without any, the longest window under REF_MAX; if every segment is
    longer than that, the first REF_MAX seconds of the first one.
    """
    best, best_key = None, None
    for i, first in enumerate(segments):
        for j in range(i, len(segments)):
            span = segments[j].end - first.start
            if span > REF_MAX:
                break
            speech = sum(s.duration for s in segments[i : j + 1])
            key = (span >= REF_MIN, speech / span if span >= REF_MIN else span)
            if best_key is None or key > best_key:
                best, best_key = (first.start, segments[j].end), key
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
