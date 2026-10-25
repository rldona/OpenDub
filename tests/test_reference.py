import math
import wave

import numpy as np
import pytest

from opendub import reference
from opendub.models import Segment


def test_pick_reference_prefers_window_with_most_speech():
    segs = [
        Segment(1, 0.0, 4.0, "a"), Segment(2, 7.0, 11.0, "b"),  # 0–11 s, 3 s of pauses
        Segment(3, 20.0, 26.0, "c"), Segment(4, 26.2, 31.0, "d"),  # 20–31 s, almost no pauses
    ]
    assert reference.pick_reference(segs) == (20.0, 31.0)


def test_pick_reference_without_long_enough_window_takes_longest_short_one():
    segs = [Segment(1, 0.0, 3.0, "a"), Segment(2, 30.0, 36.0, "b")]
    assert reference.pick_reference(segs) == (30.0, 36.0)


def test_pick_reference_cuts_a_single_long_segment():
    assert reference.pick_reference([Segment(1, 5.0, 40.0, "a")]) == (5.0, 5.0 + reference.REF_MAX)
    with pytest.raises(SystemExit):
        reference.pick_reference([])


@pytest.mark.parametrize("f0", [120.0, 210.0])
def test_mean_f0_of_a_harmonic_tone(tmp_path, f0):
    sr = 16000
    t = np.arange(sr * 2) / sr
    tone = sum(0.3 / k * np.sin(2 * math.pi * f0 * k * t) for k in (1, 2, 3))
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((tone * 32767).astype(np.int16).tobytes())
    assert reference.mean_f0(path) == pytest.approx(f0, rel=0.03)
