"""Metrics shared by the voice benchmarks (imported by run.py, which declares the dependencies).

- cer: character error rate of whisper's Spanish transcription against the text.
- p_es: whisper's probability that the clip is Spanish, without forcing the
  language (a proxy for a foreign accent).
- similarity: cosine of speaker embeddings (resemblyzer and SpeechBrain ECAPA)
  against a reference recording.
- jitter: mean pitch change between consecutive 10 ms voiced frames, in semitones.
- tremor: share of the 0.5–20 Hz modulation of pitch and of loudness that falls
  in 3–9 Hz, over voiced runs of 300 ms or more (audible trembling lives there).
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from functools import cache
from pathlib import Path

import numpy as np

SR = 16000
HOP = 160  # 10 ms


def load16k(path: Path, ss: float | None = None, to: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(ss), "-to", str(to)] if ss is not None else [])
    cmd += ["-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32).copy()


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def cer(reference: str, hypothesis: str) -> float:
    r, h = _norm(reference), _norm(hypothesis)
    row = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        prev, row[0] = row[0], i
        for j, hc in enumerate(h, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rc != hc))
    return row[len(h)] / max(len(r), 1)


@cache
def _whisper():
    import torch  # noqa: F401  (loads the CUDA libraries faster-whisper needs)
    from faster_whisper import WhisperModel

    return WhisperModel("large-v3", device="cuda", compute_type="float16")


def intelligibility(audio: np.ndarray, text: str) -> dict:
    segs, _ = _whisper().transcribe(audio, language="es", beam_size=5)
    hyp = " ".join(s.text for s in segs).strip()
    _, info = _whisper().transcribe(audio, beam_size=1)
    return {"cer": round(cer(text, hyp), 3), "p_es": round(dict(info.all_language_probs or []).get("es", 0.0), 3),
            "hyp": hyp}


@cache
def _encoders(cache_dir: str):
    from resemblyzer import VoiceEncoder
    from speechbrain.inference.speaker import EncoderClassifier

    ecapa = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", savedir=f"{cache_dir}/ecapa",
                                           run_opts={"device": "cuda"})
    return VoiceEncoder("cuda"), ecapa


def embed(audio: np.ndarray, cache_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    import torch

    rz, ecapa = _encoders(str(cache_dir))
    a = rz.embed_utterance(audio)
    with torch.no_grad():
        e = ecapa.encode_batch(torch.from_numpy(audio)[None].cuda()).squeeze().cpu().numpy()
    return a / np.linalg.norm(a), e / np.linalg.norm(e)


def similarity(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> dict:
    return {"resemblyzer": round(float(a[0] @ b[0]), 3), "ecapa": round(float(a[1] @ b[1]), 3)}


def _pitch(audio: np.ndarray):
    import librosa

    f0, voiced, _ = librosa.pyin(audio, fmin=60, fmax=400, sr=SR, frame_length=1024, hop_length=HOP)
    rms = librosa.feature.rms(y=audio, frame_length=1024, hop_length=HOP)[0][: len(f0)]
    return f0, voiced & ~np.isnan(f0), rms


def _band_share(x: np.ndarray) -> float:
    x = x - x.mean()
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), HOP / SR)
    total = spec[(freqs >= 0.5) & (freqs <= 20)].sum()
    return float(spec[(freqs >= 3) & (freqs <= 9)].sum() / total) if total > 0 else float("nan")


def voice_stability(audios: list[np.ndarray]) -> dict:
    """Median F0, jitter and 3–9 Hz tremor (pitch and loudness) over a set of clips."""
    f0s, jitter, pitch_tremor, loud_tremor = [], [], [], []
    for audio in audios:
        f0, voiced, rms = _pitch(audio)
        f = f0[voiced]
        if len(f) < 10:
            continue
        f0s.append(np.median(f))
        d = np.abs(np.diff(12 * np.log2(f)))
        jitter.append(np.mean(d[d < 2]))  # ignore octave jumps and run boundaries
        runs, cur = [], []
        for i, v in enumerate(voiced):
            if v:
                cur.append(i)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        for r in (r for r in runs if len(r) >= 30):
            pitch_tremor.append(_band_share(12 * np.log2(f0[r])))
            loud_tremor.append(_band_share(20 * np.log10(rms[r] + 1e-6)))
    return {"f0_hz": round(float(np.median(f0s)), 1) if f0s else None,
            "jitter_st": round(float(np.mean(jitter)), 3) if jitter else None,
            "pitch_tremor": round(float(np.nanmean(pitch_tremor)), 3) if pitch_tremor else None,
            "loudness_tremor": round(float(np.nanmean(loud_tremor)), 3) if loud_tremor else None,
            "voiced_runs": len(pitch_tremor)}
