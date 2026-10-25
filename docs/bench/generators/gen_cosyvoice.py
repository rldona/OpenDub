"""Fun-CosyVoice 3 0.5B (Alibaba, Apache 2.0): (A) the test sentences and (B) the dub segments.

The mode follows CosyVoice's own guidance: zero-shot (reference audio and its
transcript) when the reference is in the target language (the fixed Spanish
one), cross-lingual (audio only) when it is not (the videos' English speakers).
`speed` is its native duration control: it stretches the mel spectrogram before
the vocoder, so (B) uses it like IndexTTS's duration_factor (factor = 1/speed).
Run with its venv, from its repo (work/_bench/cosyvoice3/repo):

    ../.venv/bin/python -I <this file> [name]
"""
import sys
import time
from pathlib import Path

import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

sys.path[:0] = [".", "third_party/Matcha-TTS"]
from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "cosyvoice3"
PREFIX = "You are a helpful assistant.<|endofprompt|>"

t0 = time.monotonic()
model = AutoModel(model_dir="../pretrained_models/Fun-CosyVoice3-0.5B")
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)


def synth(text: str, ref: Path, ref_text: str, out: Path, factor: float) -> None:
    speed = 1.0 / factor
    if ref.stem == "fixed_es":
        gen = model.inference_zero_shot(text, PREFIX + ref_text, str(ref), stream=False, speed=speed,
                                        text_frontend=False)
    else:
        gen = model.inference_cross_lingual(PREFIX + text, str(ref), stream=False, speed=speed, text_frontend=False)
    wav = torch.cat([o["tts_speech"] for o in gen], dim=1)
    torchaudio.save(str(out), wav.cpu(), model.sample_rate)


common.warm_up(synth)
common.sentences(NAME, synth, load_s, {"sample_rate": model.sample_rate})
common.fit(NAME, synth, native_speed=True)
