import math
import struct
import wave

import pytest
from dataclasses import replace

from opendub import tts
from opendub.config import Settings
from opendub.models import Segment


@pytest.mark.parametrize(
    "duration, slot, seg_dur, min_tempo, expected",
    [
        (2.0, 3.0, 2.5, 1.0, 1.0),  # fits: left untouched
        (3.3, 3.0, 2.5, 1.0, 1.1),  # sped up just enough
        (5.0, 3.0, 2.5, 1.0, 1.25),  # does not fit even at the maximum
        (1.0, 3.0, 2.5, 1.0, 1.0),  # short, not slowed down by default
        (2.25, 3.0, 2.5, 0.85, 0.9),  # with min_tempo<1 it slows down to fill the segment…
        (1.0, 3.0, 2.5, 0.85, 0.85),  # …but not below the minimum
    ],
)
def test_choose_tempo(duration, slot, seg_dur, min_tempo, expected):
    assert math.isclose(tts.choose_tempo(duration, slot, seg_dur, min_tempo, 1.25), expected)


def test_slots_reach_next_segment_or_media_end():
    segs = [Segment(1, 0.0, 2.0, "a"), Segment(2, 3.5, 5.0, "b")]
    assert tts._slots(segs, 10.0) == [3.5, 6.5]


def _tone(path, seconds, silence=0.3, rate=24000):
    """Write a wav with a `seconds`-long tone surrounded by silence."""
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
    clip = tts._process(Segment(7, 1.0, 2.5, "x"), 1.8, raw, tmp_path, Settings(), tts.Voice.edge(Settings()))
    assert 1.9 < clip.raw_duration < 2.15  # without the silence at the edges
    assert math.isclose(clip.tempo, clip.raw_duration / 1.8, abs_tol=0.01)
    assert clip.overflow < 0.05
    assert (tmp_path / "0007.wav").exists()


def test_process_logs_overflow_when_too_long(tmp_path):
    raw = tmp_path / "raw.wav"
    _tone(raw, 3.0)
    clip = tts._process(Segment(1, 0.0, 1.5, "x"), 1.5, raw, tmp_path, Settings(), tts.Voice.edge(Settings()))
    assert clip.tempo == 1.25
    assert clip.overflow > 0.8


@pytest.mark.parametrize("rate", ["+0%", "-10%", "+5%", "-50%"])
def test_check_rate_accepts_edge_tts_format(rate):
    assert tts.check_rate(rate) == rate


@pytest.mark.parametrize("rate", ["-10", "10%", "-0.9", "-100%", ""])
def test_check_rate_rejects_bad_values(rate):
    with pytest.raises(SystemExit):
        tts.check_rate(rate)


def test_raw_cache_key_depends_on_rate(tmp_path):
    from opendub.workdir import WorkDir

    wd = WorkDir(tmp_path, "vid")
    a = tts._raw_path(wd, tts.Voice("edge", "es-ES-AlvaroNeural", "+0%"), "Hola.")
    b = tts._raw_path(wd, tts.Voice("edge", "es-ES-AlvaroNeural", "-10%"), "Hola.")
    assert a != b
    assert a == tts._raw_path(wd, tts.Voice("edge", "es-ES-AlvaroNeural", "+0%"), "Hola.")


def test_raw_cache_key_of_cloned_voice_depends_on_reference_and_seed(tmp_path):
    from opendub.workdir import WorkDir

    wd = WorkDir(tmp_path, "vid")
    ref_a, ref_b = tmp_path / "a.wav", tmp_path / "b.wav"
    ref_a.write_bytes(b"a")
    ref_b.write_bytes(b"b")
    s = Settings(tts="clone")
    a = tts._raw_path(wd, tts.Voice.clone(s, ref_a), "Hola.")
    assert a.suffix == ".wav"
    assert a == tts._raw_path(wd, tts.Voice.clone(s, ref_a, label="other"), "Hola.")
    assert a != tts._raw_path(wd, tts.Voice.clone(s, ref_b), "Hola.")
    assert a != tts._raw_path(wd, tts.Voice.clone(s, ref_a, seed=1), "Hola.")
    ix = tts.Voice.clone(Settings(tts="clone", engine="indextts"), ref_a)
    assert tts._raw_path(wd, ix, "Hola.") != a
    assert tts._raw_path(wd, ix, "Hola.") != tts._raw_path(wd, replace(ix, factor=0.8), "Hola.")


def _c(id, text, raw, slot=10.0, overflow=0.0):
    return tts.Clip(id=id, start=0.0, slot=slot, raw_duration=raw, tempo=1.0, duration=raw,
                    overflow=overflow, file=f"tts/{id:04d}.wav", text=text)


def test_shorten_target_fits_at_max_tempo():
    clip = _c(1, "x" * 40, raw=4.0, slot=2.0)
    assert tts.shorten_target("x" * 40, clip, 1.25) == 23  # 40·2·1.25/4 = 25, minus 5%


def test_suspicious_flags_empty_and_too_fast_clips():
    clips = [_c(i, "a" * 34, raw=2.0) for i in range(1, 6)]  # 17 chars/s
    clips.append(_c(6, "a" * 34, raw=0.5))  # 68 chars/s: cut off
    clips.append(_c(7, "a" * 34, raw=6.0))  # 5.7 chars/s: repetitions or noise
    clips.append(_c(8, "Sí.", raw=0.1))  # practically empty
    clips.append(_c(9, "Vale.", raw=1.5))  # short: not judged by speed
    assert [c.id for c in tts.suspicious(clips)] == [6, 7, 8]


def test_run_shortens_clips_that_do_not_fit(tmp_path, monkeypatch):
    import json as _json

    from opendub import translate
    from opendub.models import save_segments
    from opendub.workdir import WorkDir

    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(_json.dumps({"duration": 6.0}))  # 2nd segment's slot: 3 s
    save_segments(wd.segments, [Segment(1, 0.0, 2.0, "Short."), Segment(2, 3.0, 5.0, "Long original.")])
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "Corta."), Segment(2, 3.0, 5.0, "x" * 80)])

    async def no_check(voice):
        return None

    def fake_render(wd_, jobs, slots, settings, regenerate=False):
        # 20 chars/s unaccelerated: the clip fits if len(text)/20 <= slot·1.25
        out = []
        for s, _voice in jobs:
            raw = len(s.text) / 20
            dur = min(raw, raw / min(raw / slots[s.id], 1.25)) if raw > slots[s.id] else raw
            out.append(tts.Clip(s.id, s.start, slots[s.id], raw, round(raw / dur, 3), dur,
                                max(dur - slots[s.id], 0), f"tts/{s.id:04d}.wav", s.text))
        return out

    calls = []

    def fake_shorten(items, voice, settings, style=None, genders=None):
        calls.append(items)
        return {i: "y" * m for i, _o, _t, m in items}

    monkeypatch.setattr(tts, "_check_voice", no_check)
    monkeypatch.setattr(tts, "_render_jobs", fake_render)
    monkeypatch.setattr(translate, "shorten", fake_shorten)
    clips = tts.run(wd, Settings())

    assert len(calls) == 1 and calls[0][0][:3] == (2, "Long original.", "x" * 80)
    assert clips[1].text.startswith("y") and clips[1].overflow == 0
    assert clips[0].text == "Corta."
    assert tts.load_clips(wd)[1].text == clips[1].text


def test_fit_pace_separates_overhead_from_rate():
    # 1.5 s per clip + 20 chars/s, as IndexTTS measured on a real video
    samples = [(n, 1.5 + n / 20) for n in (10, 11, 24, 50, 60, 78, 140)]
    assert tts.fit_pace(samples) == tts.Pace(20.0, 1.5)
    # no overhead to find: a plain rate
    assert tts.fit_pace([(10, 1.0), (20, 2.0), (40, 4.0)]).overhead == 0.0
    # degenerate (longer text, shorter clip): plain rate, no negative overhead
    assert tts.fit_pace([(10, 2.0), (40, 1.0)]) == tts.Pace(round(50 / 3, 2))


def test_pace_limits_short_slots_by_overhead():
    pace = tts.Pace(20.0, 1.5)
    assert pace.seconds(30) == 3.0
    assert pace.max_chars(4.0) == 50  # (4 - 1.5) · 20
    assert pace.max_chars(1.0) == 6  # never below 30% of the plain rate
    assert tts.Pace(15.0).max_chars(4.0) == 60  # no overhead: as before


def test_shorten_target_leaves_out_the_overhead():
    clip = _c(1, "x" * 50, raw=4.0, slot=3.0)  # 1.5 s overhead + 2.5 s for 50 chars
    assert tts.shorten_target("x" * 50, clip, 1.0) == 35  # proportional: 50·3/4, minus 5%
    assert tts.shorten_target("x" * 50, clip, 1.0, overhead=1.5) == 28  # (3-1.5)/(4-1.5)·50, minus 5%


def test_fit_pace_ignores_a_garbled_calibration_clip():
    # real IndexTTS calibration: "Vamos allá." (11 chars) came out 8 s long
    samples = [(55, 5.53), (78, 6.97), (62, 5.43), (51, 4.57), (57, 6.87), (10, 2.46), (11, 8.07), (24, 4.34),
               (134, 9.80)]
    pace = tts.fit_pace(samples)
    assert pace.overhead <= tts.MAX_OVERHEAD_S and 15 < pace.cps < 21
    assert tts.fit_pace(samples + [(11, 2.0)]).overhead < 2.5  # still sane with more points
