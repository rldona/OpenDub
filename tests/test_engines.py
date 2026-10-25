"""Engines in their own venv: the shared JSON-lines client, CosyVoice's wiring, --keep-translation.

The engines themselves only run in test_cosyvoice_smoke, which is skipped unless
CosyVoice is installed and OPENTRANSLATOR_SMOKE=1 (it takes the GPU for ~30 s).
"""

import json
import os
import sys
import wave
from pathlib import Path

import pytest

from opentranslator import cosyvoice, engines, tts
from opentranslator.config import Settings
from opentranslator.models import Segment, save_segments
from opentranslator.workdir import WorkDir

FAKE_WORKER = '''
import json, sys
print(json.dumps({"ready": True, "device": "fake", "load_s": 0.1}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req["text"] == "boom":
        print(json.dumps({"id": req["id"], "ok": False, "error": "ValueError: boom"}), flush=True)
        continue
    open(req["out"], "w").write(json.dumps(req))
    print(json.dumps({"id": req["id"], "ok": True, "seconds": 0.0}), flush=True)
'''


def test_worker_speaks_json_lines_and_reports_failures(tmp_path):
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER)
    started = []

    def start():
        started.append(1)
        return engines.Worker("fake", Path(sys.executable), script, [], tmp_path, tmp_path / "fake.log")

    try:
        out = tmp_path / "a.wav"
        engines.worker("fake", start).request("Hola.", tmp_path / "ref.wav", out, 0.8, 3, lang="ES")
        req = json.loads(out.read_text())
        assert req == {"id": 1, "text": "Hola.", "ref": str((tmp_path / "ref.wav").resolve()), "out": str(out.resolve()),
                       "duration_factor": 0.8, "seed": 3, "lang": "ES"}
        with pytest.raises(RuntimeError, match="fake failed on 'boom': ValueError: boom"):
            engines.worker("fake", start).request("boom", tmp_path / "ref.wav", tmp_path / "b.wav", 1.0, 0)
        engines.worker("fake", start).request("Otra.", tmp_path / "ref.wav", tmp_path / "c.wav", 1.0, 0)
        assert len(started) == 1  # one process for every clip
    finally:
        engines.shutdown("fake")
    assert "fake" not in engines._workers


def test_cosyvoice_is_a_native_duration_engine(tmp_path, monkeypatch):
    settings = Settings(tts="clone", engine="cosyvoice", cosyvoice_dir=tmp_path / "cv", work_root=tmp_path)
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref")
    voice = tts.Voice.clone(settings, ref)
    assert voice.engine == "cosyvoice" and tts.native_duration("cosyvoice")
    assert tts.calibration_factor("cosyvoice") == 1.0 and tts.engine_model("cosyvoice") == cosyvoice.MODEL
    # the factor is part of a clip's cache key, as for IndexTTS
    wd = WorkDir(tmp_path, "vid")
    assert tts._raw_path(wd, voice, "Hola.") != tts._raw_path(wd, voice.__class__(**{**voice.__dict__, "factor": 0.8}), "Hola.")

    calls = []
    monkeypatch.setattr(cosyvoice, "synthesize", lambda *args: calls.append(args))
    out = tmp_path / "x.raw.wav"
    tts._synthesize_jobs([("Son 3 terremotos.", out, voice.__class__(**{**voice.__dict__, "factor": 0.8}))], settings)
    home, log_path, text, ref_, out_, factor, seed = calls[0]
    assert home == tmp_path / "cv" and log_path == tmp_path / "cosyvoice.log"
    assert text == "Son tres terremotos." and factor == 0.8 and out_ == out  # figures spelled out


def test_cosyvoice_not_installed_says_how_to_install(tmp_path):
    with pytest.raises(SystemExit, match="setup-engine cosyvoice"):
        cosyvoice._start(tmp_path / "nowhere", tmp_path / "cv.log")


def test_keep_translation_reuses_another_engines_translation(tmp_path, monkeypatch):
    from opentranslator import translate

    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"language": "en"}))
    save_segments(wd.segments, [Segment(1, 0.0, 2.0, "Hello.")])
    save_segments(wd.translation, [Segment(1, 0.0, 2.0, "Hola, hecho para otro motor.")])
    wd.mark_done("translate", {"made": "for chatterbox"})

    def no_claude(*args, **kwargs):
        raise AssertionError("the translation was redone")

    monkeypatch.setattr(translate, "_call_claude", no_claude, raising=False)
    monkeypatch.setattr(tts, "voice_rate", no_claude)
    kept = translate.run(wd, Settings(tts="clone", engine="cosyvoice", keep_translation=True, work_root=tmp_path))
    assert [s.text for s in kept] == ["Hola, hecho para otro motor."]
    assert wd.has("tts") is False and wd.has("translate")  # nothing downstream was marked done

    with pytest.raises(AssertionError, match="redone"):  # without the flag, the new engine's pace is needed
        translate.run(wd, Settings(tts="clone", engine="cosyvoice", work_root=tmp_path))


@pytest.mark.skipif(not (os.environ.get("OPENTRANSLATOR_SMOKE") and cosyvoice.installed(Settings().cosyvoice_dir)),
                    reason="CosyVoice not installed, or OPENTRANSLATOR_SMOKE not set")
def test_cosyvoice_smoke(tmp_path):
    """The real worker: one sentence at its natural pace and at 0.7, as 24 kHz 16-bit PCM."""
    ref = next(Path("work").glob("*/clone_ref.wav"), None)
    if ref is None:
        pytest.skip("no clone_ref.wav in work/ to clone")
    worker = cosyvoice._start(Settings().cosyvoice_dir, tmp_path / "cv.log")
    try:
        durations = []
        for factor in (1.0, 0.7):
            out = tmp_path / f"{factor}.wav"
            worker.request("Los terremotos son uno de los desastres naturales más comunes.", ref, out, factor, 0)
            with wave.open(str(out)) as w:
                assert w.getframerate() == 24000 and w.getsampwidth() == 2
                durations.append(w.getnframes() / w.getframerate())
        assert durations[1] == pytest.approx(durations[0] * 0.7, rel=0.05)
    finally:
        worker.close()
