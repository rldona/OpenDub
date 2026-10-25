"""pyannote community-1 on one recording: `run_pyannote.py <audio> <out.json>` (HF_TOKEN in the env).

Uses the exclusive diarization (one speaker at a time), which is what a dub needs.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SR, load, write  # noqa: E402


def main() -> None:
    import torch
    from pyannote.audio import Pipeline

    audio, out = Path(sys.argv[1]), Path(sys.argv[2])
    t0 = time.monotonic()
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=os.environ["HF_TOKEN"])
    pipe.to(torch.device("cuda"))
    load_s = time.monotonic() - t0
    started = time.monotonic()
    wave = torch.from_numpy(load(audio)).unsqueeze(0)
    result = pipe({"waveform": wave, "sample_rate": SR})
    ann = result.exclusive_speaker_diarization
    turns = [(seg.start, seg.end, spk) for seg, _, spk in ann.itertracks(yield_label=True)]
    write(out, "pyannote-community-1", turns, started, load_s)


if __name__ == "__main__":
    main()
