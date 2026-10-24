"""Voice cloning with Chatterbox Multilingual V3 (`--tts clone --engine chatterbox`), and
the whisper quality check shared by every cloning engine.

The reference (reference.py) is cut from the separated vocals, so cloning needs
the `separate` phase. Chatterbox clones from
the audio alone (no transcript needed) and has no speaking-rate control, so
slot fitting relies on atempo and sentence shortening as with edge-tts.
Every clip carries Resemble AI's inaudible Perth watermark.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .log import log

MODEL = "chatterbox-multilingual-v3"
SAMPLE_RATE = 24000
QC_MAX_CER = 0.3  # whisper character error rate above which a clip is redone
# On very short texts one misheard word swings the rate: "Ups, llénalo" failed on a fine clip
QC_SHORT_CHARS, QC_SHORT_MAX_CER = 20, 0.6
INSTALL_HINT = "Install the optional dependencies with: uv sync --extra clone"

_model = None
_whisper: dict[str, object] = {}  # quality-check model, loaded once per run (several check rounds)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load():
    global _model
    if _model is None:
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError:
            raise SystemExit(f"chatterbox-tts is not installed. {INSTALL_HINT}")
        device = _device()
        log.info(f"Loading {MODEL} ({device})…")
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    return _model


def unload() -> None:
    """Drop the Chatterbox and quality-check whisper models (the next use loads them again)."""
    global _model
    _model = None
    _whisper.clear()
_whisper: dict[str, object] = {}  # quality-check model, loaded once per run (several check rounds)


def synthesize(text: str, ref: Path, seed: int, out: Path) -> None:
    """Speak `text` with the voice of `ref` and write it as a 24 kHz mono wav."""
    import torch

    model = _load()
    torch.manual_seed(seed)
    wav = model.generate(text, language_id="es", audio_prompt_path=str(ref))
    pcm = (np.clip(wav.squeeze(0).cpu().numpy(), -1.0, 1.0) * 32767).astype(np.int16)
    tmp = out.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(model.sr)
        w.writeframes(pcm.tobytes())
    tmp.rename(out)


def normalize(text: str) -> str:
    """Lowercase, no punctuation, figures written out: "Llegó 4x4" ≈ "llego cuatro por cuatro"."""
    from .spoken import spell_numbers

    text = unicodedata.normalize("NFC", spell_numbers(text).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def cer(reference_text: str, hypothesis: str) -> float:
    """Character error rate between two texts, ignoring case and punctuation."""
    r, h = normalize(reference_text), normalize(hypothesis)
    row = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        prev, row[0] = row[0], i
        for j, hc in enumerate(h, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (rc != hc))
    return row[len(h)] / max(len(r), 1)


def unintelligible(clips: list[tuple[int, Path, str]], whisper_model: str) -> set[int]:
    """Ids of the clips whose whisper transcription strays too far from their text."""
    model = _whisper.get(whisper_model)
    if model is None:
        from faster_whisper import WhisperModel  # lazy import: slow to load

        from .transcribe import whisper_device

        device, compute_type = whisper_device()
        model = _whisper[whisper_model] = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    bad = set()
    for clip_id, path, text in clips:
        # decoded with ffmpeg to avoid faster-whisper's PyAV decoder, as in transcribe
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True, check=True,
        ).stdout
        # greedy: half the time of beam search, same verdict on 352 of 353 real clips
        segments, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), language="es", beam_size=1,
                                       without_timestamps=True, condition_on_previous_text=False)
        limit = QC_SHORT_MAX_CER if len(normalize(text)) < QC_SHORT_CHARS else QC_MAX_CER
        if cer(text, " ".join(s.text for s in segments)) > limit:
            bad.add(clip_id)
    return bad
