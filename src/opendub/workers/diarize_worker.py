"""Diarization worker: who speaks when, with NVIDIA Nemotron 3 Diarization.

Runs once per video in the Nemotron venv (engines/nemotron, `setup-engine nemotron`):

    python diarize_worker.py <model.nemo> <audio> <out.json>

Writes {"turns": [[start, end, "speaker_N"], ...], "load_s", "seconds"}: one
speaker at a time, speakers numbered by first arrival. The offline configuration
of the model card (30.4 s buffer) is the one benchmarked in docs/bench/diarize.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

SR = 16000
# the model card's "very high latency (offline)" configuration, in 80 ms frames
OFFLINE = {"spkcache_len": 264, "fifo_len": 40, "chunk_len": 340, "chunk_right_context": 40,
           "spkcache_update_period": 300}


def load(path: Path):
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def main() -> None:
    model_path, audio, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    t0 = time.monotonic()
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SortformerEncLabelModel.restore_from(restore_path=str(model_path), map_location=device, strict=False)
    model.eval()
    for name, value in OFFLINE.items():
        setattr(model.sortformer_modules, name, value)
    model._check_streaming_parameters()
    load_s = time.monotonic() - t0
    started = time.monotonic()
    with torch.inference_mode():
        segments = model.diarize(audio=[load(audio)], batch_size=1, sample_rate=SR)
    turns = []
    for line in segments[0]:  # "begin end speaker_N"
        a, b, spk = str(line).replace(",", " ").split()[:3]
        turns.append([round(float(a), 3), round(float(b), 3), spk])
    out.write_text(json.dumps({"turns": sorted(turns), "device": device, "load_s": round(load_s, 1),
                               "seconds": round(time.monotonic() - started, 1)}))


if __name__ == "__main__":
    main()
