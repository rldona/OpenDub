import sys
import types

from opentranslator import transcribe


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
