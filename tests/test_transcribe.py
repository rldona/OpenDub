import sys
import types

from opendub import transcribe


def _fake_ctranslate2(monkeypatch, gpus: int) -> None:
    module = types.SimpleNamespace(get_cuda_device_count=lambda: gpus)
    monkeypatch.setitem(sys.modules, "ctranslate2", module)


def test_whisper_device_uses_cuda_when_libs_load(monkeypatch):
    _fake_ctranslate2(monkeypatch, gpus=1)
    monkeypatch.setattr(transcribe, "_load_cuda_libs", lambda: True)
    assert transcribe.whisper_device() == ("cuda", "float16")


def test_whisper_device_falls_back_to_cpu_without_cuda_libs(monkeypatch):
    _fake_ctranslate2(monkeypatch, gpus=1)
    monkeypatch.setattr(transcribe, "_load_cuda_libs", lambda: False)
    assert transcribe.whisper_device() == ("cpu", "int8")


def test_whisper_device_cpu_without_gpu(monkeypatch):
    _fake_ctranslate2(monkeypatch, gpus=0)
    monkeypatch.setattr(transcribe, "_load_cuda_libs", lambda: True)
    assert transcribe.whisper_device() == ("cpu", "int8")


def test_videos_cut_before_fragment_joining_keep_their_segments(tmp_path, monkeypatch):
    import json

    from opendub.config import Settings
    from opendub.models import Segment, load_segments, save_segments
    from opendub.workdir import WorkDir

    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"subs": {"manual": "subs.en.vtt"}}))
    (wd.path / "subs.en.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:00.600\nI\n\n"
                                         "00:00:02.000 --> 00:00:04.000\nwant to redesign this character.\n")
    old = [Segment(1, 0.0, 0.6, "I"), Segment(2, 2.0, 4.0, "want to redesign this character.")]
    save_segments(wd.segments, old)
    wd.mark_done("transcribe", {"source": "manual", "whisper_model": None})  # as cut before segments v2
    regroup = transcribe.regroup
    monkeypatch.setattr(transcribe, "regroup", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-cut")))
    assert transcribe.run(wd, Settings()) == old  # its translation and hand edits stay valid
    monkeypatch.setattr(transcribe, "regroup", regroup)
    fresh = transcribe.run(wd, Settings(), force=True)
    assert [s.text for s in fresh] == ["I want to redesign this character."]
    assert load_segments(wd.segments) == fresh
