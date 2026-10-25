"""Transcripts of the dub references (audio/fit/<video>_clone_ref.wav), for engines that need one.

Fish S2 Pro and CosyVoice 3 condition on the reference's text as well as its audio.
Run in OpenDub's env: uv run docs/bench/generators/ref_texts.py
"""
from pathlib import Path

from faster_whisper import WhisperModel

from opendub.transcribe import _load_cuda_libs, _load_wav, whisper_device

FIT = Path(__file__).resolve().parent.parent / "audio" / "fit"

_load_cuda_libs()
device, compute_type = whisper_device()
model = WhisperModel("large-v3", device=device, compute_type=compute_type)
for ref in sorted(FIT.glob("*_clone_ref.wav")):
    segments, _ = model.transcribe(_load_wav(ref), language="en", beam_size=5)
    text = " ".join(s.text.strip() for s in segments)
    ref.with_suffix(".txt").write_text(text + "\n")
    print(f"{ref.name}: {text}")
