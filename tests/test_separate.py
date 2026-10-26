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


def _tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * separate.SAMPLE_RATE)) / separate.SAMPLE_RATE
    return np.stack([0.5 * np.sin(2 * np.pi * 440 * t), 0.25 * np.sin(2 * np.pi * 220 * t)]).astype(np.float32)


def _wav(path):
    import wave

    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, 2).T / 32767


def test_the_stem_writer_and_the_decoder_round_trip(tmp_path):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("needs ffmpeg")
    audio = _tone(1.0)
    writer = separate._Writer(tmp_path / "stems" / "x.wav")
    writer.write(audio[:, :1000])
    writer.write(audio[:, 1000:])
    writer.close()
    assert not list((tmp_path / "stems").glob("*.part.wav"))
    with separate._stream(tmp_path / "stems" / "x.wav") as proc:
        back = separate._read(proc.stdout, 10 * separate.SAMPLE_RATE)
    assert back.shape == audio.shape and np.abs(back - audio).max() < 1e-3


class _Stream:
    """A decoder's stdout over an array: f32le stereo bytes, served in uneven reads."""

    def __init__(self, audio):
        self.data = audio.T.astype(np.float32).tobytes()
        self.pos = 0

    def read(self, n):
        n = min(n, 7777)  # a pipe gives what it has, not what was asked for
        piece = self.data[self.pos: self.pos + n]
        self.pos += len(piece)
        return piece


def _fake_model(window):
    """A model whose stems depend on each sample and its neighbours, as a real one does: a seam would show."""
    smooth = np.apply_along_axis(lambda c: np.convolve(c, np.ones(5) / 5, mode="same"), 1, window)
    return {"vocals": 0.6 * window, "drums": 0.3 * window, "other": 0.1 * smooth}


@pytest.mark.parametrize("seconds", [0.2, 1.0, 2.5, 3.0, 3.3])
def test_separating_by_chunks_gives_the_whole_separation(tmp_path, seconds):
    audio = _tone(seconds)
    sr = separate.SAMPLE_RATE
    voc, bg = separate._Writer(tmp_path / "v.wav"), separate._Writer(tmp_path / "b.wav")
    seen = []
    n = separate.separate_stream(_Stream(audio), lambda w: seen.append(w.shape[1]) or _fake_model(w), voc, bg,
                                 chunk=sr // 2, overlap=sr // 10)
    voc.close()
    bg.close()
    assert n == audio.shape[1] and max(seen) <= sr // 2 + sr // 10  # never more than a chunk and its overlap
    whole_v, whole_b = separate.split_stems(_fake_model(audio))
    got_v, got_b = _wav(tmp_path / "v.wav"), _wav(tmp_path / "b.wav")
    assert got_v.shape == audio.shape and got_b.shape == audio.shape
    assert np.abs(got_v - whole_v).max() < 1e-3  # linear and pointwise: exactly the same
    assert np.abs(got_b - whole_b).max() < 2e-3  # the smoothed stem differs only at the window edges, faded


def test_split_stems_needs_more_than_the_vocals():
    with pytest.raises(ValueError, match="only the vocals"):
        separate.split_stems({"vocals": np.ones((2, 4), dtype=np.float32)})
