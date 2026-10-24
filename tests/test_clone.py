import math
from dataclasses import replace

import pytest

from opentranslator import clone, tts
from opentranslator.config import Settings
from opentranslator.models import Segment, save_segments
from opentranslator.workdir import WorkDir


def test_pick_reference_prefers_window_with_most_speech():
    segs = [
        Segment(1, 0.0, 4.0, "a"), Segment(2, 7.0, 11.0, "b"),  # 0–11 s, 3 s of pauses
        Segment(3, 20.0, 26.0, "c"), Segment(4, 26.2, 31.0, "d"),  # 20–31 s, almost no pauses
    ]
    assert clone.pick_reference(segs) == (20.0, 31.0)


def test_pick_reference_without_long_enough_window_takes_longest_short_one():
    segs = [Segment(1, 0.0, 3.0, "a"), Segment(2, 30.0, 36.0, "b")]
    assert clone.pick_reference(segs) == (30.0, 36.0)


def test_pick_reference_cuts_a_single_long_segment():
    assert clone.pick_reference([Segment(1, 5.0, 40.0, "a")]) == (5.0, 5.0 + clone.REF_MAX)
    with pytest.raises(SystemExit):
        clone.pick_reference([])


def test_cer_ignores_case_and_punctuation():
    assert clone.cer("¿Qué es la IA?", "qué es la ia") == 0.0
    assert math.isclose(clone.cer("hola", "hola mundo"), 6 / 4)
    assert clone.cer("abcd", "abxd") == 0.25


def _clip(seg: Segment, voice: tts.Voice) -> tts.Clip:
    raw = len(seg.text) / 15
    return tts.Clip(seg.id, seg.start, 10.0, raw, 1.0, raw, 0.0, f"tts/{seg.id:04d}.wav", seg.text, voice.label)


def test_repair_chain_keeps_the_cloned_voice_as_long_as_possible(tmp_path, monkeypatch):
    from opentranslator import translate

    wd = WorkDir(tmp_path, "vid")
    segs = [Segment(i, i * 10.0, i * 10.0 + 3, f"Frase número {i} del vídeo.") for i in (1, 2, 3)]
    save_segments(wd.segments, [replace(s, text=f"Sentence {s.id}.") for s in segs])
    ref, fixed = tmp_path / "ref.wav", tmp_path / "fixed.wav"
    ref.write_bytes(b"ref")
    fixed.write_bytes(b"fixed")
    settings = Settings(tts="clone", clone_ref=fixed)
    voice = tts.Voice.clone(settings, ref)
    voices = {s.id: voice for s in segs}
    clips = {s.id: _clip(s, voice) for s in segs}
    by_id = {s.id: s for s in segs}

    # clip 1 is fixed by another seed, clip 2 by shortening; clip 3 never passes
    passes = {1: {"clone (seed+1)"}, 2: {"clone (shortened)"}, 3: set()}

    def fake_failures(wd_, ids, clips_, settings_):
        return {i for i in ids if clips_[i].voice == "clone" or clips_[i].voice not in passes[i] | {"edge"}}

    rendered = []

    def fake_render_each(wd_, jobs, slots, settings_, regenerate=False):
        rendered.append(sorted((s.id, v.label) for s, v in jobs))
        return [_clip(s, v) for s, v in jobs]

    monkeypatch.setattr(tts, "_clone_failures", fake_failures)
    monkeypatch.setattr(tts, "_render_each", fake_render_each)
    monkeypatch.setattr(translate, "shorten", lambda items, v, s: {i: t[:m] for i, _o, t, m in items})

    fell_back = tts._repair_clones(wd, clips, voices, {}, by_id, settings)

    assert rendered == [
        [(1, "clone (seed+1)"), (2, "clone (seed+1)"), (3, "clone (seed+1)")],
        [(2, "clone (shortened)"), (3, "clone (shortened)")],
        [(3, "clone (fixed reference)")],
        [(3, "edge")],
    ]
    assert fell_back == {3}
    assert voices[1].seed == tts.SEED + 1 and voices[2].ref == ref and voices[3].engine == "edge"
    assert len(clips[2].text) < len(segs[1].text)


def test_repair_chain_skips_steps_that_are_off(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    seg = Segment(1, 0.0, 3.0, "Una frase.")
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    settings = Settings(tts="clone", shorten=False)  # and no --clone-ref
    voices = {1: tts.Voice.clone(settings, ref)}
    clips = {1: _clip(seg, voices[1])}
    rendered = []

    monkeypatch.setattr(tts, "_clone_failures", lambda wd_, ids, c, s: {i for i in ids if c[i].voice != "edge"})
    monkeypatch.setattr(tts, "_render_each", lambda wd_, jobs, slots, s, regenerate=False: (
        rendered.append([v.label for _, v in jobs]) or [_clip(sg, v) for sg, v in jobs]))

    assert tts._repair_clones(wd, clips, voices, {}, {1: seg}, settings) == {1}
    assert rendered == [["clone (seed+1)"], ["edge"]]


def test_voice_rate_dispatches_on_engine(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    monkeypatch.setattr(tts, "speaking_rate", lambda root, voice, rate: 17.0)
    monkeypatch.setattr(clone, "reference", lambda wd_: tmp_path / "ref.wav")
    monkeypatch.setattr(tts, "clone_speaking_rate", lambda root, ref: 14.0)
    assert tts.voice_rate(wd, Settings()) == 17.0
    assert tts.voice_rate(wd, Settings(tts="clone")) == 14.0
    with pytest.raises(SystemExit):
        tts.voice_rate(wd, Settings(tts="qwen"))
