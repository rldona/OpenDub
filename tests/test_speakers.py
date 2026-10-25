"""Several voices, second half: each speaker's voice, and a translation that knows who speaks."""

import json

import pytest

from opendub import reference, translate, tts
from opendub.config import Settings
from opendub.models import Segment, load_segments, save_segments
from opendub.workdir import WorkDir

# A speaks most (cloned), B speaks little: too little clean speech to clone, so a stock voice
SEGMENTS = [Segment(1, 0.0, 5.0, "Welcome to the show.", "A"), Segment(2, 5.2, 10.0, "Today we talk games.", "A"),
            Segment(3, 10.3, 12.0, "Thanks.", "B"), Segment(4, 12.5, 17.0, "Let's start with art.", "A")]


@pytest.fixture
def wd(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"language": "en", "duration": 20.0}))
    save_segments(wd.segments, SEGMENTS)
    save_segments(wd.translation, [Segment(s.id, s.start, s.end, f"Frase {s.id}.", s.speaker) for s in SEGMENTS])
    wd.vocals.parent.mkdir(parents=True)
    wd.vocals.write_bytes(b"wav")
    wd.diarization.write_text(json.dumps({"turns": [], "speakers": {"A": {"f0_hz": 120.0}, "B": {"f0_hz": 210.0}}}))
    cuts = []
    monkeypatch.setattr(reference, "ffmpeg", lambda *args: cuts.append(args) or open(args[-1], "wb").write(b"ref"))
    monkeypatch.setattr(reference, "mean_f0", lambda path: 120.0)
    monkeypatch.setattr(tts, "_clone_failures", lambda wd_, ids, clips, s: set())

    async def no_check(voice):
        return None

    monkeypatch.setattr(tts, "_check_voice", no_check)
    wd.cuts = cuts
    return wd


def test_each_speaker_is_cloned_from_their_own_turns_only(wd):
    ref = reference.speaker_reference(wd, "A")
    assert ref.name == "clone_ref_A.wav"
    start, end = float(wd.cuts[-1][1]), float(wd.cuts[-1][3])
    assert (start, end) == (0.0, 10.0)  # A's run before B speaks: B's "Thanks." stays out
    assert reference.speaker_reference(wd, "B") is None  # 1.7 s: not enough to clone


def test_stock_voices_follow_gender_and_variant():
    assert tts.stock_voice("es-ES-AlvaroNeural", "female") == "es-ES-ElviraNeural"
    assert tts.stock_voice("es-ES-AlvaroNeural", "male") == "es-ES-AlvaroNeural"
    assert tts.stock_voice("es-MX-JorgeNeural", "female") == "es-MX-DaliaNeural"
    assert tts.stock_voice("es-ES-ElviraNeural", None) == "es-ES-ElviraNeural"
    assert tts.gender_of(210.0) == "female" and tts.gender_of(120.0) == "male" and tts.gender_of(None) is None


def _renderer(log):
    def fake_render(wd_, jobs, slots, settings, regenerate=False):
        out = []
        for seg, voice in jobs:
            log.append((seg.id, voice.engine, voice.name if voice.engine == "edge" else voice.ref.name))
            raw = len(seg.text) / 15
            out.append(tts.Clip(seg.id, seg.start, slots[seg.id], raw, 1.0, raw, 0.0, f"tts/{seg.id:04d}.wav",
                                seg.text, voice.label, voice.factor))
        return out
    return fake_render


def test_a_dub_with_several_voices_gives_each_speaker_theirs(wd, monkeypatch):
    rendered = []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered))
    settings = Settings(tts="clone", engine="chatterbox", multi_speaker=True)
    tts.run(wd, settings)
    assert sorted(rendered) == [(1, "chatterbox", "clone_ref_A.wav"), (2, "chatterbox", "clone_ref_A.wav"),
                                (3, "edge", "es-ES-ElviraNeural"), (4, "chatterbox", "clone_ref_A.wav")]
    index = json.loads(wd.tts_index.read_text())
    assert index["speakers"] == {"1": "A", "2": "A", "3": "B", "4": "A"}
    assert index["speaker_voices"]["B"]["voice"] == "es-ES-ElviraNeural"
    assert index["speaker_voices"]["A"]["stock"] == "es-ES-AlvaroNeural"

    # without the option, the same video is dubbed with one voice as before
    rendered.clear()
    tts.run(wd, Settings(tts="clone", engine="chatterbox"), force=True)
    assert {r[2] for r in rendered} == {"clone_ref.wav"}


def test_a_speaker_change_is_retouched_like_an_edit(wd, monkeypatch):
    rendered = []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered))
    settings = Settings(tts="clone", engine="chatterbox", multi_speaker=True)
    tts.run(wd, settings)
    segs = load_segments(wd.translation)
    segs[2].speaker = "A"  # "Thanks." was A's after all
    save_segments(wd.translation, segs)
    assert tts.pending_edits(wd) == {3}
    rendered.clear()
    assert tts.retouch(wd, Settings()) == [3]  # the dub's own voices, whatever settings say
    assert rendered == [(3, "chatterbox", "clone_ref_A.wav")]


def test_the_last_resort_keeps_the_speakers_gender(wd, monkeypatch):
    rendered = []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered))
    monkeypatch.setattr(tts, "_clone_failures", lambda wd_, ids, clips, s: {i for i in ids if clips[i].voice != "edge"})
    settings = Settings(tts="clone", engine="chatterbox", multi_speaker=True, shorten=False)
    tts.run(wd, settings)
    final = {c.id: c.voice for c in tts.load_clips(wd)}
    assert final == {1: "edge", 2: "edge", 3: "edge", 4: "edge"}
    assert (1, "edge", "es-ES-AlvaroNeural") in rendered  # A is a man: Álvaro, not Elvira


def test_the_translation_caps_each_sentence_at_its_speakers_pace(wd, monkeypatch):
    monkeypatch.setattr(tts, "speaker_paces", lambda wd_, s, segs: {"A": tts.Pace(10.0), "B": tts.Pace(20.0)})
    seen = []

    def fake_cli(system, prompt, model):
        seen.append((system, json.loads(prompt)))
        return {"segments": [{"id": s["id"], "text": "ok"} for s in json.loads(prompt)["segments"]]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    translate.run(wd, Settings(tts="clone", multi_speaker=True, batch_size=10), force=True)
    system, payload = seen[0]
    first, thanks = payload["segments"][0], payload["segments"][2]
    assert (first["speaker"], first["gender"], first["max_chars"]) == ("A", "male", 52)  # 5.2 s at 10 chars/s
    assert (thanks["speaker"], thanks["gender"], thanks["max_chars"]) == ("B", "female", 44)  # 2.2 s to the next one, at 20
    assert "cansado/cansada" in system

    seen.clear()
    translate.run(wd, Settings(tts="clone", batch_size=10, chars_per_second=15), force=True)
    assert "speaker" not in seen[0][1]["segments"][0]  # one voice: as before


def test_shortening_knows_who_says_it(monkeypatch):
    seen = {}

    def fake_cli(system, prompt, model):
        seen["system"], seen["items"] = system, json.loads(prompt)
        return {"segments": [{"id": 3, "text": "Corta."}]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    translate.shorten([(3, "I'm tired.", "Estoy muy cansada hoy.", 12)], "es-ES-AlvaroNeural", Settings(),
                      genders={3: "female"})
    assert seen["items"][0]["speaker_gender"] == "female" and "speaker_gender" in seen["system"]
