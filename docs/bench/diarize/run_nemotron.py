"""NVIDIA Nemotron 3 Diarization on one recording, offline configuration (30.4 s buffer):
`run_nemotron.py <audio> <out.json>`.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SR, load, write  # noqa: E402

# the model card's "very high latency (offline)" configuration, in 80 ms frames
OFFLINE = {"spkcache_len": 264, "fifo_len": 40, "chunk_len": 340, "chunk_right_context": 40,
           "spkcache_update_period": 300}


def main() -> None:
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    audio, out = Path(sys.argv[1]), Path(sys.argv[2])
    t0 = time.monotonic()
    model = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization").eval().to("cuda")
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
        turns.append((float(a), float(b), spk))
    write(out, "nemotron-3-diarization", turns, started, load_s)


if __name__ == "__main__":
    main()
