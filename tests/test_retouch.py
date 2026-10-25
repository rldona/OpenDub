"""Retouch: speak again only the edited sentences and the takes asked for (retouch.retouch)."""

import json

import pytest

from opendub import reference, repair, retouch, translate, tts
from opendub.config import Settings
from opendub.models import Segment, load_segments, save_segments
from opendub.workdir import WorkDir


@pytest.fixture
def wd(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"duration": 20.0}))
    save_segments(wd.segments, [Segment(i, i * 4.0, i * 4.0 + 3, f"Original sentence {i}.") for i in range(1, 5)])
    save_segments(wd.translation, [Segment(i, i * 4.0, i * 4.0 + 3, f"Frase {i}.") for i in range(1, 5)])
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    monkeypatch.setattr(reference, "reference", lambda wd_: ref)
    monkeypatch.setattr(reference, "mean_f0", lambda path: 200.0)

    async def no_check(voice):
        return None

    monkeypatch.setattr(tts, "_check_voice", no_check)
    monkeypatch.setattr(repair, "clone_failures", lambda wd_, ids, clips, s: set())
    return wd


def _renderer(log, chars_per_s=15.0):
    def fake_render(wd_, jobs, slots, settings, regenerate=False):
        out = []
        for seg, voice in jobs:
            clip = wd_.path / f"tts/{seg.id:04d}.wav"  # as the real render leaves it (tts.clips_exist)
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"")
            log.append((seg.id, seg.text, voice.seed))
            raw = len(seg.text) / chars_per_s
            tempo = min(max(raw / slots[seg.id], 1.0), settings.max_tempo)
            dur = raw / tempo
            out.append(tts.Clip(seg.id, seg.start, slots[seg.id], raw, round(tempo, 3), dur,
                                round(max(dur - slots[seg.id], 0), 3), f"tts/{seg.id:04d}.wav", seg.text,
                                voice.label, voice.factor))
        return out
    return fake_render


def _edit(wd, sid, text):
    """As the web saves an edit (web/videos.save_translation)."""
    segs = load_segments(wd.translation)
    for s in segs:
        if s.id == sid:
            s.text = text
    save_segments(wd.translation, segs)
    edits = json.loads(wd.translation_edits.read_text()) if wd.translation_edits.exists() else {}
    edits[str(sid)] = {"source": f"Original sentence {sid}.", "text": text}
    wd.translation_edits.write_text(json.dumps(edits))
    wd.invalidate_from("tts")


def test_retouch_speaks_only_the_edits_and_marks_tts_done(wd, monkeypatch):
    rendered = []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered))
    settings = Settings(tts="clone", engine="chatterbox")
    tts.run(wd, settings)
    assert len(rendered) == 4 and retouch.pending_edits(wd) == set()

    _edit(wd, 3, "Frase tres, corregida.")
    assert retouch.pending_edits(wd) == {3}
    rendered.clear()
    assert retouch.retouch(wd, settings) == [3]
    assert rendered == [(3, "Frase tres, corregida.", tts.SEED)]
    index = json.loads(wd.tts_index.read_text())
    assert [c["text"] for c in index["clips"]][2] == "Frase tres, corregida."
    assert index["stats"]["retouched"] == [3] and index["sources"]["3"] == "Frase tres, corregida."
    assert retouch.pending_edits(wd) == set()

    # the phase is cached for the current translation: a full run speaks nothing
    rendered.clear()
    tts.run(wd, settings)
    assert rendered == []


def test_another_take_uses_the_next_seed_and_a_full_run_keeps_it(wd, monkeypatch):
    rendered = []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered))
    settings = Settings(tts="clone", engine="chatterbox")
    tts.run(wd, settings)
    rendered.clear()
    retouch.retouch(wd, settings, [2])
    retouch.retouch(wd, settings, [2])
    assert rendered == [(2, "Frase 2.", tts.SEED + 1), (2, "Frase 2.", tts.SEED + 2)]
    assert retouch.takes(wd) == {2: tts.SEED + 2}

    rendered.clear()
    tts.run(wd, settings, force=True)
    assert (2, "Frase 2.", tts.SEED + 2) in rendered and (1, "Frase 1.", tts.SEED) in rendered


def test_hand_edits_are_never_shortened(wd, monkeypatch):
    rendered, asked = [], []
    monkeypatch.setattr(tts, "_render_jobs", _renderer(rendered, chars_per_s=8.0))
    monkeypatch.setattr(translate, "shorten", lambda items, v, s, st=None, g=None: asked.extend(i for i, *_ in items) or
                        {i: "Corta." for i, *_ in items})
    settings = Settings(tts="clone", engine="chatterbox")
    tts.run(wd, settings)
    long = "Una frase editada a mano que es bastante más larga que su hueco."
    _edit(wd, 2, long)
    retouch.retouch(wd, settings)
    assert asked == []  # it doesn't fit, but it is said as written
    clip = next(c for c in tts.load_clips(wd) if c.id == 2)
    assert clip.text == long and clip.tempo == settings.max_tempo and clip.overflow > 0
    assert any(line.startswith("#2 @") for line in wd.overflow_log.read_text().splitlines())


def test_retouch_patches_overflow_log_and_drops_mix_lines(wd, monkeypatch):
    monkeypatch.setattr(tts, "_render_jobs", _renderer([]))
    settings = Settings(tts="clone", engine="chatterbox")
    tts.run(wd, settings)
    wd.overflow_log.write_text("#1 @4.00s: lasts 4.00s at 1.25x, slot 4.00s (+0.10s) · Frase 1.\n"
                               "#3 @12.00s: lasts 4.00s at 1.25x, slot 4.00s (+0.10s) · Frase 3.\n"
                               "#2 delayed 0.10s in the mix\n")
    _edit(wd, 3, "Tres.")
    retouch.retouch(wd, settings)
    assert wd.overflow_log.read_text() == "#1 @4.00s: lasts 4.00s at 1.25x, slot 4.00s (+0.10s) · Frase 1.\n"


def test_retouch_refuses_what_it_cannot_do(wd, monkeypatch):
    monkeypatch.setattr(tts, "_render_jobs", _renderer([]))
    with pytest.raises(SystemExit):
        retouch.retouch(wd, Settings())  # no dub yet
    tts.run(wd, Settings())  # edge-tts
    with pytest.raises(SystemExit):
        retouch.retouch(wd, Settings(), [2])  # edge-tts has no takes
    with pytest.raises(SystemExit):
        retouch.retouch(wd, Settings(), [99])
    assert retouch.retouch(wd, Settings()) == []  # nothing pending
