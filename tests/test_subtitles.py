"""T-34: the translation out to subtitles with speakers and back, without losing times, texts or speakers."""

import json

import pytest

from opendub import speakers, subtitles
from opendub.models import Segment, load_segments, save_segments
from opendub.workdir import WorkDir


@pytest.fixture
def wd(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    originals = [Segment(1, 0.5, 3.25, "Hi, I'm Ivan.", "A"), Segment(2, 3.8, 7.125, "And I'm Gabby.", "B"),
                 Segment(3, 8.0, 11.0, "Welcome, everyone.", "A")]
    save_segments(wd.segments, originals)
    save_segments(wd.translation, [Segment(1, 0.5, 3.25, "Hola, soy Iván.", "A"),
                                   Segment(2, 3.8, 7.125, "Y yo, Gabby.", "B"),
                                   Segment(3, 8.0, 11.0, "Bienvenidos, todos.", "A")])
    wd.diarization.write_text(json.dumps({"turns": [], "speakers": {"A": {}, "B": {}}}))
    speakers.rename(wd, "A", "Iván")
    return wd


@pytest.mark.parametrize("fmt", ["vtt", "ass"])
def test_a_round_trip_keeps_times_texts_and_speakers(wd, fmt):
    path = subtitles.export(wd, fmt)
    cues = subtitles.parse(path.name, path.read_text(encoding="utf-8"))
    assert [(c.text, c.speaker) for c in cues] == [("Hola, soy Iván.", "Iván"), ("Y yo, Gabby.", "B"),
                                                  ("Bienvenidos, todos.", "Iván")]
    exact = 3 if fmt == "vtt" else 2  # ASS keeps centiseconds, its own precision
    assert [(round(c.start, exact), round(c.end, exact)) for c in cues] == [
        (0.5, 3.25), (3.8, round(7.125, exact)), (8.0, 11.0)]
    assert subtitles.import_cues(wd, cues) == {"texts": [], "speakers": []}  # unchanged: nothing to save
    assert not wd.translation_edits.exists()


def test_corrected_subtitles_come_back_as_hand_edits_and_speakers(wd):
    text = subtitles.export(wd, "vtt").read_text(encoding="utf-8")
    text = text.replace("<v B>Y yo, Gabby.", "<v B>Y yo soy Gabby.").replace("<v Iván>Bienvenidos, todos.",
                                                                            "<v B>Bienvenidos a todos.")
    wd.mark_done("tts", {})
    done = subtitles.import_cues(wd, subtitles.parse("fixed.vtt", text))
    assert done == {"texts": [2, 3], "speakers": [3]}
    segs = load_segments(wd.translation)
    assert [(s.text, s.speaker) for s in segs] == [("Hola, soy Iván.", "A"), ("Y yo soy Gabby.", "B"),
                                                  ("Bienvenidos a todos.", "B")]
    assert [(s.start, s.end) for s in segs] == [(0.5, 3.25), (3.8, 7.125), (8.0, 11.0)]  # times are the original's
    edits = json.loads(wd.translation_edits.read_text())
    assert edits["2"] == {"source": "And I'm Gabby.", "text": "Y yo soy Gabby."}  # as the web editor saves them
    assert speakers.load(wd)["segments"] == {"3": "B"} and not wd.has("tts")  # the voice is behind: retouch


def test_an_ass_from_another_editor_matches_by_start_time(wd):
    ass = subtitles.export(wd, "ass").read_text(encoding="utf-8")
    line = next(x for x in ass.splitlines() if x.endswith("Y yo, Gabby."))
    ass = ass.replace(line, "Dialogue: 0,0:00:03.82,0:00:07.00,Default,B,0,0,0,,{\\i1}Y yo{\\i0}, Gabby, encantada.")
    done = subtitles.import_cues(wd, subtitles.parse("fixed.ass", ass))
    assert done["texts"] == [2] and load_segments(wd.translation)[1].text == "Y yo, Gabby, encantada."


def test_a_cue_with_no_sentence_or_an_unknown_name_saves_nothing(wd):
    before = wd.translation.read_text()
    with pytest.raises(ValueError, match="No sentence starts"):
        subtitles.import_cues(wd, [subtitles.Cue(1.0, 2.0, "Cambiado."), subtitles.Cue(20.0, 21.0, "Sobra.")])
    with pytest.raises(ValueError, match="No speaker called 'Bea'"):
        subtitles.import_cues(wd, [subtitles.Cue(0.5, 3.25, "Otro texto.", "Bea")])
    assert wd.translation.read_text() == before and not wd.translation_edits.exists()


def test_srt_has_no_speaker_and_unknown_formats_are_refused(wd):
    cues = subtitles.parse("x.srt", subtitles.export(wd, "srt").read_text(encoding="utf-8"))
    assert [c.speaker for c in cues] == [None, None, None] and cues[1].text == "Y yo, Gabby."
    with pytest.raises(ValueError, match="Unknown subtitle format"):
        subtitles.parse("x.txt", "")
