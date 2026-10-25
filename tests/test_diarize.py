"""Several voices, first half: who speaks when (diarize.py) and sentences that say whose they are."""

import json

import pytest

from opendub import diarize, media, transcribe
from opendub.config import Settings
from opendub.models import Segment, load_segments, save_segments
from opendub.segments import Piece, regroup
from opendub.workdir import WorkDir


def _words(text, start, step=0.3):
    """Word-level pieces, as whisper gives them."""
    out = []
    for i, w in enumerate(text.split()):
        out.append(Piece(start + i * step, start + (i + 1) * step - 0.02, w))
    return out


def test_sentences_split_where_the_speaker_changes():
    pieces = _words("Welcome Andy and Valerie, how are you doing", 0.0) + _words("Good, thanks for having us.", 2.75)
    turns = [[0.0, 2.7, "C"], [2.75, 5.0, "A"]]
    segs = regroup(pieces, turns=turns)
    assert [(s.speaker, s.text) for s in segs] == [
        ("C", "Welcome Andy and Valerie, how are you doing"), ("A", "Good, thanks for having us.")]
    assert regroup(pieces)[0].speaker is None  # without turns: as before


def test_a_word_or_two_of_another_speaker_inside_a_sentence_stays_with_it():
    pieces = _words("Yep, we had some audio issues before.", 0.0)
    turns = [[0.0, 0.6, "C"], [0.6, 1.2, "B"], [1.2, 3.0, "C"]]  # "we had" given to B
    [seg] = regroup(pieces, turns=turns)
    assert (seg.speaker, seg.text) == ("C", "Yep, we had some audio issues before.")


def test_fragments_never_join_another_speakers_sentence():
    pieces = [Piece(0.0, 0.5, "So"), Piece(1.5, 4.0, "this is a whole new sentence.")]
    assert len(regroup(pieces, turns=[[0.0, 0.5, "A"], [1.5, 4.0, "B"]])) == 2
    assert len(regroup(pieces, turns=[[0.0, 0.5, "A"], [1.5, 4.0, "A"]])) == 1  # same speaker: joined


def test_a_manual_cue_goes_to_whoever_says_most_of_it():
    [seg] = regroup([Piece(0.0, 4.0, "A whole subtitle cue")], turns=[[0.0, 1.0, "B"], [1.0, 4.0, "A"]])
    assert seg.speaker == "A"


def test_speakers_need_enough_speech_and_are_named_by_it():
    turns = [[0, 40, "speaker_1"], [40, 41, "speaker_2"], [41, 100, "speaker_0"], [100, 105, "speaker_2"]]
    kept_turns, kept, dropped = diarize.keep_speakers(turns)
    assert kept == {"A": 59.0, "B": 40.0} and dropped == {"speaker_2": 6.0}
    assert [t[2] for t in kept_turns] == ["B", "A"]
    _, kept, _ = diarize.keep_speakers([[0, 10, "speaker_0"]])  # a short video: still its one voice
    assert kept == {"A": 10.0}


def test_single_voice_segments_are_saved_as_before(tmp_path):
    path = tmp_path / "s.json"
    save_segments(path, [Segment(1, 0.0, 1.0, "Hola."), Segment(2, 1.0, 2.0, "Adiós.", "B")])
    rows = json.loads(path.read_text())
    assert "speaker" not in rows[0] and rows[1]["speaker"] == "B"
    assert load_segments(path)[1].speaker == "B"


@pytest.fixture
def wd(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"language": "en", "subs": {"manual": "subs.vtt"}}))
    (wd.path / "subs.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello there.\n\n"
                                      "00:00:02.500 --> 00:00:04.000\nHi, nice to meet you.\n")
    return wd


def test_transcription_uses_the_diarization_only_with_several_voices(wd):
    transcribe.run(wd, Settings())
    assert {s.speaker for s in load_segments(wd.segments)} == {None}
    with pytest.raises(SystemExit):
        transcribe.run(wd, Settings(multi_speaker=True))  # no diarization yet
    wd.diarization.write_text(json.dumps({"turns": [[0.0, 2.0, "A"], [2.5, 4.0, "B"]]}))
    segs = transcribe.run(wd, Settings(multi_speaker=True))
    assert [s.speaker for s in segs] == ["A", "B"]
    wd.diarization.write_text(json.dumps({"turns": [[0.0, 4.0, "A"]]}))  # a new diarization: cut again
    assert {s.speaker for s in transcribe.run(wd, Settings(multi_speaker=True))} == {"A"}


def test_diarize_runs_the_worker_once_and_caches(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    wd.vocals.parent.mkdir(parents=True)
    wd.vocals.write_bytes(b"wav")
    home = tmp_path / "nemotron"
    python, model = diarize.paths(home)
    with pytest.raises(SystemExit, match="setup-engine nemotron"):
        diarize.run(wd, Settings(nemotron_dir=home))
    python.parent.mkdir(parents=True)
    python.write_text("")
    model.parent.mkdir(parents=True)
    model.write_text("")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        turns = [[0, 50, "speaker_0"], [50, 52, "speaker_1"], [52, 120, "speaker_2"]]
        open(cmd[-1], "w").write(json.dumps({"turns": turns, "seconds": 1.0, "device": "cuda"}))
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(media, "run", fake_run)
    monkeypatch.setattr(diarize, "_pitch", lambda vocals, turns, s: {"A": 210.0, "B": 120.0}[s])
    data = diarize.run(wd, Settings(nemotron_dir=home))
    assert data["speakers"] == {"A": {"seconds": 68.0, "f0_hz": 210.0}, "B": {"seconds": 50.0, "f0_hz": 120.0}}
    assert data["dropped"] == {"speaker_1": 2.0}
    diarize.run(wd, Settings(nemotron_dir=home))
    assert len(calls) == 1  # cached
