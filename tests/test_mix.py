import wave

import numpy as np

from opendub import mix
from opendub.tts import SAMPLE_RATE, Clip


def _clip(id, start, duration):
    return Clip(id=id, start=start, slot=duration, raw_duration=duration, tempo=1.0,
                duration=duration, overflow=0.0, file=f"tts/{id:04d}.wav")


def test_place_keeps_timestamps_when_clips_fit():
    placements = mix.place([_clip(1, 0.0, 1.0), _clip(2, 2.0, 1.0)])
    assert [(p.start, p.delay) for p in placements] == [(0.0, 0.0), (2.0, 0.0)]


def test_place_pushes_overlapping_clips_and_recovers():
    clips = [_clip(1, 0.0, 3.0), _clip(2, 2.0, 1.0), _clip(3, 3.5, 1.0), _clip(4, 10.0, 1.0)]
    placements = mix.place(clips, min_gap=0.1)
    assert [p.start for p in placements] == [0.0, 3.1, 4.2, 10.0]
    assert [p.delay for p in placements] == [0.0, 1.1, 0.7, 0.0]


def _write(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.asarray(samples) * 32767).astype(np.int16).tobytes())


def test_compose_places_audio_and_cuts_at_end(tmp_path):
    one_s = np.full(SAMPLE_RATE, 0.5, dtype=np.float32)
    _write(tmp_path / "tts/0001.wav", one_s)
    _write(tmp_path / "tts/0002.wav", one_s)
    clips = [_clip(1, 0.5, 1.0), _clip(2, 2.5, 1.0)]
    track, cut = mix.compose(clips, mix.place(clips), tmp_path, total=3.0)
    assert len(track) == 3 * SAMPLE_RATE
    assert track[int(0.4 * SAMPLE_RATE)] == 0
    assert abs(track[int(1.0 * SAMPLE_RATE)] - 0.5) < 1e-3
    assert abs(track[int(2.9 * SAMPLE_RATE)] - 0.5) < 1e-3
    assert cut == 1  # the second clip runs past the end


def test_filter_graph_cases(tmp_path):
    from opendub.config import Settings

    bg = tmp_path / "background.wav"
    inputs, graph = mix.filter_graph(Settings(bg_volume_db=-15), bg)
    assert inputs == [] and "[0:a]volume=-15dB" in graph

    inputs, graph = mix.filter_graph(Settings(separate=True, music_volume_db=-3), bg)
    assert inputs == ["-i", str(bg)] and "[2:a]aresample=48000,volume=-3dB" in graph
    assert "[0:a]" not in graph

    inputs, graph = mix.filter_graph(Settings(separate=True, mute_original=True), bg)
    assert inputs == [] and "amix" not in graph
