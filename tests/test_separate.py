import numpy as np
import pytest

from opendub import separate


def test_resolve_backend(monkeypatch):
    monkeypatch.setattr(separate.sys, "platform", "darwin")
    monkeypatch.setattr(separate.platform, "machine", lambda: "arm64")
    assert separate.resolve_backend("auto") == "mlx"
    monkeypatch.setattr(separate.sys, "platform", "linux")
    monkeypatch.setattr(separate.platform, "machine", lambda: "x86_64")
    assert separate.resolve_backend("auto") == "torch"
    assert separate.resolve_backend("mlx") == "mlx"
    with pytest.raises(SystemExit):
        separate.resolve_backend("spleeter")


def test_split_stems_sums_everything_but_vocals():
    ones = np.ones((2, 4), dtype=np.float32)
    stems = {"drums": ones * 0.1, "bass": ones * 0.2, "other": ones * 0.3, "vocals": ones * 0.5}
    vocals, background = separate.split_stems(stems)
    assert np.allclose(vocals, 0.5)
    assert np.allclose(background, 0.6)
    with pytest.raises(ValueError):
        separate.split_stems({"drums": ones})


def test_save_and_load_roundtrip(tmp_path):
    t = np.arange(separate.SAMPLE_RATE) / separate.SAMPLE_RATE
    audio = np.stack([0.5 * np.sin(2 * np.pi * 440 * t), 0.25 * np.sin(2 * np.pi * 220 * t)]).astype(np.float32)
    path = tmp_path / "stems" / "x.wav"
    separate._save(path, audio)
    back = separate._load(path)
    assert back.shape == audio.shape
    assert np.abs(back - audio).max() < 1e-3
