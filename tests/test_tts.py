import math
import struct
import wave

import pytest

from opentranslator import tts
from opentranslator.config import Settings
from opentranslator.models import Segment


@pytest.mark.parametrize(
    "duration, slot, seg_dur, min_tempo, expected",
    [
        (2.0, 3.0, 2.5, 1.0, 1.0),  # cabe: no se toca
        (3.3, 3.0, 2.5, 1.0, 1.1),  # acelera lo justo
        (5.0, 3.0, 2.5, 1.0, 1.25),  # no cabe ni al máximo
        (1.0, 3.0, 2.5, 1.0, 1.0),  # corto, sin ralentizar por defecto
        (2.25, 3.0, 2.5, 0.85, 0.9),  # con min_tempo<1 ralentiza para llenar el segmento…
        (1.0, 3.0, 2.5, 0.85, 0.85),  # …pero no por debajo del mínimo
    ],
)
def test_choose_tempo(duration, slot, seg_dur, min_tempo, expected):
    assert math.isclose(tts.choose_tempo(duration, slot, seg_dur, min_tempo, 1.25), expected)


def test_slots_reach_next_segment_or_media_end():
    segs = [Segment(1, 0.0, 2.0, "a"), Segment(2, 3.5, 5.0, "b")]
    assert tts._slots(segs, 10.0) == [3.5, 6.5]


def _tone(path, seconds, silence=0.3, rate=24000):
    """Escribe un wav con un tono de `seconds` rodeado de silencio."""
    pad = [0] * int(silence * rate)
    tone = [int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(seconds * rate))]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(pad) * 2 + len(tone)}h", *pad, *tone, *pad))


def test_process_trims_silence_and_speeds_up(tmp_path):
    raw = tmp_path / "raw.wav"
    _tone(raw, 2.0)
    clip = tts._process(Segment(7, 1.0, 2.5, "x"), 1.8, raw, tmp_path, Settings())
    assert 1.9 < clip.raw_duration < 2.15  # sin el silencio de los bordes
    assert math.isclose(clip.tempo, clip.raw_duration / 1.8, abs_tol=0.01)
    assert clip.overflow < 0.05
    assert (tmp_path / "0007.wav").exists()


def test_process_logs_overflow_when_too_long(tmp_path):
    raw = tmp_path / "raw.wav"
    _tone(raw, 3.0)
    clip = tts._process(Segment(1, 0.0, 1.5, "x"), 1.5, raw, tmp_path, Settings())
    assert clip.tempo == 1.25
    assert clip.overflow > 0.8
