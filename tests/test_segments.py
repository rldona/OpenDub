import json

from opentranslator.segments import Piece, clean_text, parse_json3, parse_vtt, regroup


def test_clean_text_removes_noise():
    assert clean_text("[Music] hello &amp; <i>bye</i> (laughs)") == "hello & bye"
    assert clean_text("- Hi.\n- Hello.") == "Hi. Hello."
    assert clean_text("♪ ♪") == ""


def test_parse_json3_manual_and_word_level(tmp_path):
    data = {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Hello there."}]},
            {"tStartMs": 3000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
            {
                "tStartMs": 4000,
                "dDurationMs": 1500,
                "segs": [{"utf8": "how"}, {"utf8": " are", "tOffsetMs": 400}, {"utf8": " you", "tOffsetMs": 900}],
            },
        ]
    }
    path = tmp_path / "s.json3"
    path.write_text(json.dumps(data))
    pieces = parse_json3(path)
    assert [p.text.strip() for p in pieces] == ["Hello there.", "how", "are", "you"]
    assert pieces[2].start == 4.4 and pieces[2].end == 4.9
    assert pieces[3].end == 5.5


def test_parse_vtt_rolling_asr_dedup(tmp_path):
    # Formato típico del ASR de YouTube: cada línea aparece dos veces
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000 align:start position:0%
hello<00:00:01.500><c> world</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
hello world

00:00:03.010 --> 00:00:05.000 align:start position:0%
hello world
this<00:00:03.600><c> is</c><00:00:04.000><c> fine</c>
"""
    path = tmp_path / "s.vtt"
    path.write_text(vtt)
    pieces = parse_vtt(path)
    assert [p.text.strip() for p in pieces] == ["hello", "world", "this", "is", "fine"]
    assert pieces[1].start == 1.5
    assert pieces[2].start == 3.01


def test_parse_vtt_plain_cues(tmp_path):
    vtt = """WEBVTT

1
00:00:01.200 --> 00:00:03.360
All right, so here we are,
in front of the elephants

2
00:01:05.318 --> 00:01:07.974
the cool thing
"""
    path = tmp_path / "s.vtt"
    path.write_text(vtt)
    pieces = parse_vtt(path)
    assert pieces[0].text == "All right, so here we are, in front of the elephants"
    assert pieces[1].start == 65.318


def test_regroup_joins_until_sentence_end():
    pieces = [
        Piece(0.0, 2.0, "When new content is created"),
        Piece(2.1, 4.0, "by AI,"),
        Piece(4.1, 6.0, "it's called generative AI."),
        Piece(6.2, 8.0, "Next sentence."),
    ]
    segs = regroup(pieces)
    assert [s.text for s in segs] == [
        "When new content is created by AI, it's called generative AI.",
        "Next sentence.",
    ]
    assert (segs[0].start, segs[0].end) == (0.0, 6.0)
    assert [s.id for s in segs] == [1, 2]


def test_regroup_splits_on_gap_and_max_duration():
    gap = regroup([Piece(0, 1, "a"), Piece(3, 4, "b")])
    assert len(gap) == 2
    words = [Piece(i, i + 0.9, f"w{i}") for i in range(30)]
    long = regroup(words, max_dur=12)
    assert all(s.duration <= 12 for s in long)
    assert len(long) == 3


def test_regroup_splits_sentences_inside_a_cue():
    segs = regroup([Piece(0, 10, "First sentence here. Second one that is longer.")])
    assert [s.text for s in segs] == ["First sentence here.", "Second one that is longer."]
    assert segs[0].end == segs[1].start
    assert 3.5 < segs[0].end < 4.5


def test_regroup_merges_very_short_sentences():
    segs = regroup([Piece(0, 0.5, "Yes."), Piece(0.6, 2.0, "We did it.")])
    assert [s.text for s in segs] == ["Yes. We did it."]


def test_regroup_fixes_overlaps():
    segs = regroup([Piece(0, 3, "One."), Piece(2, 4, "Two words.")])
    assert segs[0].end == 2
