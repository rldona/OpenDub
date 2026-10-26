import math
from dataclasses import replace

import pytest

from opendub import clone, reference, repair, tts
from opendub.config import Settings
from opendub.models import Segment, save_segments
from opendub.workdir import WorkDir


def test_cer_ignores_case_and_punctuation():
    assert clone.cer("¿Qué es la IA?", "qué es la ia") == 0.0
    assert math.isclose(clone.cer("hola", "hola mundo"), 6 / 4)
    assert clone.cer("abcd", "abxd") == 0.25


def _clip(seg: Segment, voice: tts.Voice) -> tts.Clip:
    raw = len(seg.text) / 15
    return tts.Clip(seg.id, seg.start, 10.0, raw, 1.0, raw, 0.0, f"tts/{seg.id:04d}.wav", seg.text, voice.label)


def test_repair_chain_keeps_the_cloned_voice_as_long_as_possible(tmp_path, monkeypatch):
    from opendub import translate

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
    passes = {1: {"chatterbox (seed+1)"}, 2: {"chatterbox (shortened)"}, 3: set()}

    def fake_failures(wd_, ids, clips_, settings_):
        return {i for i in ids if clips_[i].voice == "chatterbox" or clips_[i].voice not in passes[i] | {"edge"}}

    rendered = []

    def fake_render_each(wd_, jobs, slots, settings_, regenerate=False):
        rendered.append(sorted((s.id, v.label) for s, v in jobs))
        return [_clip(s, v) for s, v in jobs]

    monkeypatch.setattr(repair, "clone_failures", fake_failures)
    monkeypatch.setattr(tts, "_render_each", fake_render_each)
    monkeypatch.setattr(translate, "shorten", lambda items, v, s, st=None, g=None: {i: t[:m] for i, _o, t, m in items})

    fell_back = repair.repair_clones(repair.Fitting(wd, clips, voices, {}, by_id, settings))

    assert rendered == [
        [(1, "chatterbox (seed+1)"), (2, "chatterbox (seed+1)"), (3, "chatterbox (seed+1)")],
        [(2, "chatterbox (shortened)"), (3, "chatterbox (shortened)")],
        [(3, "chatterbox (fixed reference)")],
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

    monkeypatch.setattr(repair, "clone_failures", lambda wd_, ids, c, s: {i for i in ids if c[i].voice != "edge"})
    monkeypatch.setattr(tts, "_render_each", lambda wd_, jobs, slots, s, regenerate=False: (
        rendered.append([v.label for _, v in jobs]) or [_clip(sg, v) for sg, v in jobs]))

    assert repair.repair_clones(repair.Fitting(wd, clips, voices, {}, {1: seg}, settings)) == {1}
    assert rendered == [["chatterbox (seed+1)"], ["edge"]]


def test_voice_rate_dispatches_on_engine(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    monkeypatch.setattr(tts, "speaking_rate", lambda root, voice, rate: 17.0)
    monkeypatch.setattr(reference, "reference", lambda wd_: tmp_path / "ref.wav")
    monkeypatch.setattr(tts, "cloned_speaking_rate",
                        lambda settings, voice: tts.Pace({"chatterbox": 14.0, "indextts": 12.0}[voice.engine], 1.0))
    assert tts.voice_rate(wd, Settings()) == tts.Pace(17.0)
    assert tts.voice_rate(wd, Settings(tts="clone")) == tts.Pace(14.0, 1.0)
    assert tts.voice_rate(wd, Settings(tts="clone", engine="indextts")) == tts.Pace(12.0, 1.0)
    assert tts.voice_rate(wd, Settings(tts="clone", engine="auto")).cps == 14.0  # one voice → chatterbox
    with pytest.raises(SystemExit):
        tts.voice_rate(wd, Settings(tts="qwen"))
    with pytest.raises(SystemExit):
        tts.voice_rate(wd, Settings(tts="clone", engine="qwen"))


def test_tiny_texts_are_judged_by_duration_only():
    assert tts.tiny("Yo") and tts.tiny("¿Sí?") and tts.tiny(" Y. ") and not tts.tiny("Hola") and not tts.tiny("Yo sé.")
    voice = tts.Voice("chatterbox", "es-ES-AlvaroNeural", "-10%")

    def seg(i, text):
        return Segment(i, i * 10.0, i * 10.0 + 3, text)

    clips = [_clip(seg(i, f"Una frase normal número {i}."), voice) for i in range(1, 6)]
    fine = replace(_clip(seg(6, "Yo"), voice), raw_duration=0.6)
    garbled = replace(_clip(seg(7, "Yo"), voice), raw_duration=3.2)  # a cloned "Yo" that ran away
    assert [c.id for c in tts.suspicious([*clips, fine, garbled])] == [7]


def test_quality_check_never_shortens_a_tiny_text(tmp_path, monkeypatch):
    from opendub import translate

    wd = WorkDir(tmp_path, "vid")
    segs = [Segment(1, 0.0, 3.0, "Yo"), Segment(2, 5.0, 8.0, "Una frase larga que no se entiende.")]
    save_segments(wd.segments, [Segment(1, 0.0, 3.0, "I"), Segment(2, 5.0, 8.0, "A long sentence.")])
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    settings = Settings(tts="clone")
    voice = tts.Voice.clone(settings, ref)
    voices = {s.id: voice for s in segs}
    clips = {s.id: _clip(s, voice) for s in segs}
    rendered, asked = [], []

    monkeypatch.setattr(repair, "clone_failures", lambda wd_, ids, c, s: {i for i in ids if c[i].voice != "edge"})
    monkeypatch.setattr(tts, "_render_each", lambda wd_, jobs, slots, s, regenerate=False: (
        rendered.append(sorted((sg.id, v.label, sg.text) for sg, v in jobs)) or [_clip(sg, v) for sg, v in jobs]))
    monkeypatch.setattr(translate, "shorten", lambda items, v, s, st=None, g=None: asked.extend(i for i, *_ in items) or
                        {i: t[:m] for i, _o, t, m in items})

    repair.repair_clones(repair.Fitting(wd, clips, voices, {}, {s.id: s for s in segs}, settings))
    assert asked == [2]  # "Yo" is never sent to be shortened (it came back as "Y")
    assert [(i, label) for i, label, _ in rendered[1]] == [(2, "chatterbox (shortened)")]
    assert (1, "edge", "Yo") in rendered[-1]  # still says "Yo" on the last resort


def test_a_sentence_s_own_voice_is_its_reference_when_long_and_clean(tmp_path, monkeypatch):
    from opendub import voices as voices_mod

    wd = WorkDir(tmp_path, "vid")
    wd.vocals.parent.mkdir(parents=True, exist_ok=True)
    wd.vocals.write_bytes(b"vocals")
    cuts = []
    monkeypatch.setattr(reference, "ffmpeg", lambda *args: cuts.append(args) or open(args[-1], "wb").write(b"cut"))
    segs = [Segment(1, 0.0, 4.0, "Long enough and clean.", "A"), Segment(2, 4.5, 6.0, "Too short.", "A"),
            Segment(3, 7.0, 11.0, "Long, but Bea talks over it.", "A")]
    turns = [[0.0, 6.0, "A"], [7.0, 11.0, "A"], [8.0, 9.0, "B"]]
    (wd.path / "diarization.json").write_text(__import__("json").dumps({"turns": turns, "speakers": {}}))
    speaker_ref = tmp_path / "clone_ref_A.wav"
    voice = tts.Voice("chatterbox", "es-ES-AlvaroNeural", "-10%", ref=speaker_ref, label="chatterbox")
    got = voices_mod.sentence_voices(wd, segs, {s.id: voice for s in segs})
    assert got[1].ref == wd.path / "sentence_refs" / "0001.wav" and got[1].pace_ref == speaker_ref
    assert got[1].label == "chatterbox (own voice)"
    assert got[2] == voice and got[3] == voice  # too short; someone else over it
    assert [a[a.index("-ss") + 1] for a in cuts] == ["0.000"]


def test_a_sentence_s_own_voice_speaks_at_its_speaker_s_pace(tmp_path, monkeypatch):
    settings = Settings(tts="clone", work_root=tmp_path)
    speaker_ref, own = tmp_path / "ref_A.wav", tmp_path / "own.wav"
    speaker_ref.write_bytes(b"speaker")
    own.write_bytes(b"own sentence")
    (tmp_path / "voice_rates.json").write_text(__import__("json").dumps(
        {tts.cloned_rate_key("chatterbox", speaker_ref): {"cps": 15.0, "overhead": 0.4}}))
    monkeypatch.setattr(tts, "_calibrate", lambda *a: pytest.fail("a sentence's own voice was calibrated"))
    voice = tts.Voice("chatterbox", "es-ES-AlvaroNeural", "-10%", ref=own, pace_ref=speaker_ref)
    assert tts.cloned_speaking_rate(settings, voice) == tts.Pace(15.0, 0.4)


def test_a_failed_own_voice_goes_back_to_the_speaker_s_reference_first(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    seg = Segment(1, 0.0, 4.0, "Una frase con su propia voz.")
    speaker_ref, own = tmp_path / "ref.wav", tmp_path / "own.wav"
    settings = Settings(tts="clone", shorten=False)
    voices = {1: tts.Voice("chatterbox", "es-ES-AlvaroNeural", "-10%", ref=own, pace_ref=speaker_ref,
                           label="chatterbox (own voice)")}
    clips = {1: _clip(seg, voices[1])}
    rendered = []
    monkeypatch.setattr(repair, "clone_failures", lambda wd_, ids, c, s: {i for i in ids if c[i].voice != "chatterbox"})
    monkeypatch.setattr(tts, "_render_each", lambda wd_, jobs, slots, s, regenerate=False: (
        rendered.append([(v.label, v.ref) for _, v in jobs]) or [_clip(sg, v) for sg, v in jobs]))
    assert repair.repair_clones(repair.Fitting(wd, clips, voices, {}, {1: seg}, settings)) == set()
    assert rendered == [[("chatterbox", speaker_ref)]] and voices[1].pace_ref is None
