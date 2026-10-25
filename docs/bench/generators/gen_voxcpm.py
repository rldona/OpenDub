"""VoxCPM2 (OpenBMB, Apache 2.0, 48 kHz): (A) the test sentences and (B) the dub segments.

Cloning from the reference audio alone (`reference_wav_path`): the "ultimate"
mode continues from the reference and its transcript, which for an English
reference carries the English over. No numeric speed control, so (B) measures the
natural duration only. Run with its venv (work/_bench/voxcpm2):

    .venv/bin/python -I <this file> <checkpoint dir> [name]
"""
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from voxcpm import VoxCPM  # noqa: E402

CKPT = sys.argv[1]
NAME = sys.argv[2] if len(sys.argv) > 2 else "voxcpm2"

t0 = time.monotonic()
model = VoxCPM.from_pretrained(CKPT, local_files_only=True, load_denoiser=False, device="cuda")
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)


def synth(text: str, ref: Path, ref_text: str, out: Path, factor: float) -> None:
    wav = model.generate(text=text, reference_wav_path=str(ref), seed=common.SEED)
    sf.write(str(out), wav, model.tts_model.sample_rate)


common.warm_up(synth)
common.sentences(NAME, synth, load_s, {"sample_rate": model.tts_model.sample_rate})
common.fit(NAME, synth, native_speed=False)
