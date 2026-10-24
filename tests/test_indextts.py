import json
from dataclasses import replace

import pytest

from opentranslator import indextts, tts
from opentranslator.config import Settings
from opentranslator.models import Segment
from opentranslator.workdir import WorkDir


def test_fit_factor_scales_to_slot_with_margin_and_floor():
    assert indextts.fit_factor(4.0, 5.0) == 1.0  # fits: untouched
    assert indextts.fit_factor(5.0, 4.0) == pytest.approx(4.0 * 0.97 / 5.0, abs=1e-3)
    assert indextts.fit_factor(5.0, 4.0, factor=0.9) == pytest.approx(0.9 * 4.0 * 0.97 / 5.0, abs=1e-3)
    assert indextts.fit_factor(10.0, 2.0) == indextts.MIN_FACTOR


def test_resolve_engine_uses_engine_flag_only_with_clone():
    assert tts.resolve_engine(Settings()) == "edge"
    assert tts.resolve_engine(Settings(tts="clone")) == "chatterbox"
    assert tts.resolve_engine(Settings(tts="clone", engine="indextts")) == "indextts"
    assert tts.resolve_engine(Settings(tts="edge", engine="indextts")) == "edge"
    for bad in (Settings(tts="indextts"), Settings(tts="clone", engine="qwen")):
        with pytest.raises(SystemExit):
            tts.resolve_engine(bad)


def test_suspicious_judges_fitted_clips_at_their_natural_speed():
    def c(i, raw, factor=1.0):
        return tts.Clip(i, 0.0, 10.0, raw, 1.0, raw, 0.0, f"tts/{i:04d}.wav", "a" * 34, "indextts", factor)

    clips = [c(i, 2.0) for i in range(1, 6)]  # 17 chars/s
    clips.append(c(6, 1.0, factor=0.5))  # 34 chars/s, but on purpose: 17 at factor 1.0
    clips.append(c(7, 0.5))  # 68 chars/s at factor 1.0: cut off
    assert [x.id for x in tts.suspicious(clips)] == [7]


CPS = 10.0  # calibrated chars/s at indextts.CALIBRATION_FACTOR


def _fake_render(rendered):
    """Clips whose duration follows the factor exactly, running 10% longer than the calibration predicts."""

    def render(wd_, group, slots_, settings_, voice_, regenerate=False):
        rendered.append([(s.id, voice_.factor) for s in group])
        cal = indextts.CALIBRATION_FACTOR
        return [tts.Clip(s.id, s.start, slots_[s.id], len(s.text) / CPS * voice_.factor / cal * 1.1, 1.0,
                         0.0, 0.0, f"tts/{s.id:04d}.wav", s.text, voice_.label, voice_.factor) for s in group]

    return render


def test_indextts_factor_is_predicted_and_corrected_within_the_floor(tmp_path, monkeypatch):
    wd = WorkDir(tmp_path, "vid")
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    settings = Settings(tts="clone", engine="indextts")  # --min-factor 0.7
    voice = tts.Voice.clone(settings, ref)
    # 2 s, 4 s and 6 s at the calibration factor, all in 4 s slots
    segs = [Segment(1, 0.0, 2.0, "x" * 20), Segment(2, 5.0, 7.0, "x" * 40), Segment(3, 10.0, 12.0, "x" * 60)]
    slots = {1: 4.0, 2: 4.0, 3: 4.0}
    monkeypatch.setattr(tts, "cloned_speaking_rate", lambda s, v: CPS)
    rendered = []
    monkeypatch.setattr(tts, "_render", _fake_render(rendered))

    clips = {c.id: c for c in tts._render_each(wd, [(s, voice) for s in segs], slots, settings)}

    cal = indextts.CALIBRATION_FACTOR
    predicted = round(cal * 4.0 * 0.97 / 4.0, 3)
    assert sorted(sum(rendered[:3], [])) == [(1, 1.0), (2, predicted), (3, 0.7)]  # room → natural pace; 3 → floor
    first_pass = 40 / CPS * predicted / cal * 1.1  # seg 2's duration at the predicted factor
    corrected = indextts.fit_factor(first_pass, 4.0, predicted, floor=0.7)
    assert corrected > 0.7
    assert len(rendered) == 4 and rendered[3] == [(2, corrected)]  # one measured correction, still ≥ floor
    assert clips[2].raw_duration <= 4.0 and clips[2].factor >= 0.7
    assert clips[3].factor == 0.7 and clips[3].raw_duration > 4.0  # left for shortening, not compressed further


@pytest.mark.parametrize("shortening_helps", [True, False])
def test_indextts_shortens_before_going_below_the_floor(tmp_path, monkeypatch, shortening_helps):
    import json as _json

    from opentranslator import reference, translate
    from opentranslator.models import save_segments

    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(_json.dumps({"duration": 20.0}))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    save_segments(wd.segments, [Segment(1, 0.0, 2.0, "Short."), Segment(2, 4.0, 7.0, "A long original.")])
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "x" * 20), Segment(2, 4.0, 7.0, "x" * 80),
                                   Segment(3, 9.0, 10.0, "y")])  # slot of 2: 5 s

    async def no_check(voice):
        return None

    rendered, shortened = [], []

    def fake_shorten(items, voice, settings):
        shortened.append((items, [list(r) for r in rendered]))
        return {i: ("z" * (m - 5) if shortening_helps else t) for i, _o, t, m in items}

    monkeypatch.setattr(tts, "_check_voice", no_check)
    monkeypatch.setattr(reference, "reference", lambda wd_: ref)
    monkeypatch.setattr(reference, "mean_f0", lambda path: 212.0)
    monkeypatch.setattr(tts, "cloned_speaking_rate", lambda s, v: CPS)
    monkeypatch.setattr(tts, "_repair_clones", lambda *a: set())
    monkeypatch.setattr(tts, "_render", _fake_render(rendered))
    monkeypatch.setattr(translate, "shorten", fake_shorten)

    clips = tts.run(wd, Settings(tts="clone", engine="indextts"))

    # shortening is asked while no clip has gone below the floor yet
    assert shortened and all(f >= 0.7 for batch in shortened[0][1] for _, f in batch)
    assert shortened[0][0][0][0] == 2
    index = _json.loads(wd.tts_index.read_text())
    assert index["engine"] == "indextts" and index["reference_f0_hz"] == 212.0
    assert tts.load_clips(wd)[1].factor == clips[1].factor
    log = wd.overflow_log.read_text()
    if shortening_helps:
        assert clips[1].factor >= 0.7 and "below the 0.70 floor" not in log
    else:
        assert indextts.MIN_FACTOR <= clips[1].factor < 0.7 and "#2" in log and "below the 0.70 floor" in log


def test_worker_reports_missing_install(tmp_path):
    with pytest.raises(SystemExit, match="setup-indextts"):
        indextts.Worker(tmp_path / "nowhere", tmp_path / "ix.log")


def test_engine_auto_picks_by_reference_pitch(tmp_path, monkeypatch):
    from opentranslator import reference

    ref = tmp_path / "ref.wav"
    settings = Settings(tts="clone", engine="auto")
    for f0, expected in ((139.0, "indextts"), (214.0, "chatterbox"), (None, "chatterbox")):
        monkeypatch.setattr(reference, "mean_f0", lambda path, f0=f0: f0)
        assert tts.resolve_engine(settings, ref) == expected
        assert tts.Voice.clone(settings, ref).engine == expected
    assert tts.resolve_engine(Settings(tts="edge", engine="auto")) == "edge"
    with pytest.raises(ValueError):
        tts.resolve_engine(settings)  # auto needs the reference
