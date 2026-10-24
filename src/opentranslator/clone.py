"""Voice cloning with Chatterbox Multilingual V3 (`--tts clone`).

The reference is a 10–15 s stretch of the original speaker, cut from the
separated vocals, so cloning needs the `separate` phase. Chatterbox clones from
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
from .media import ffmpeg
from .models import Segment, load_segments
from .workdir import WorkDir

MODEL = "chatterbox-multilingual-v3"
SAMPLE_RATE = 24000
REF_MIN, REF_MAX = 10.0, 15.0  # seconds of reference audio
QC_MAX_CER = 0.3  # whisper character error rate above which a clip is redone
INSTALL_HINT = "Install the optional dependencies with: uv sync --extra clone"

_model = None


def pick_reference(segments: list[Segment]) -> tuple[float, float]:
    """(start, end) of the consecutive segments that make the best reference.

    Prefers windows of REF_MIN–REF_MAX seconds with the most speech (fewest
    pauses); without any, the longest window under REF_MAX; if every segment is
    longer than that, the first REF_MAX seconds of the first one.
    """
    best, best_key = None, None
    for i, first in enumerate(segments):
        for j in range(i, len(segments)):
            span = segments[j].end - first.start
            if span > REF_MAX:
                break
            speech = sum(s.duration for s in segments[i : j + 1])
            key = (span >= REF_MIN, speech / span if span >= REF_MIN else span)
            if best_key is None or key > best_key:
                best, best_key = (first.start, segments[j].end), key
    if best is None:
        if not segments:
            raise SystemExit("There are no segments to take a voice reference from")
        return segments[0].start, segments[0].start + REF_MAX
    return best


def reference(wd: WorkDir) -> Path:
    """Cut the reference clip of the original speaker from the separated vocals."""
    if not wd.vocals.exists():
        raise SystemExit("Voice cloning needs the separated vocals: run `separate` first (or use `dub`)")
    start, end = pick_reference(load_segments(wd.segments))
    path = wd.path / "clone_ref.wav"
    ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(wd.vocals),
           "-ac", "1", "-ar", str(SAMPLE_RATE), str(path))
    return path


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
    text = unicodedata.normalize("NFC", text.lower())
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
    from faster_whisper import WhisperModel  # lazy import: slow to load

    from .transcribe import whisper_device

    device, compute_type = whisper_device()
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    bad = set()
    for clip_id, path, text in clips:
        # decoded with ffmpeg to avoid faster-whisper's PyAV decoder, as in transcribe
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True, check=True,
        ).stdout
        segments, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), language="es", beam_size=5)
        if cer(text, " ".join(s.text for s in segments)) > QC_MAX_CER:
            bad.add(clip_id)
    return bad
