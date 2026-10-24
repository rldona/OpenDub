"""IndexTTS-2.5 at duration_factor 1.0 on a video's real segments, once per alternative reference.

Run with the IndexTTS venv's python from its repo. Usage:
gen_alt_refs.py <tts.json with the segment texts> <alt_refs dir> <out dir>
"""
import json
import sys
from pathlib import Path

import torch
from indextts.infer_v2_5 import IndexTTS2

texts, refs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
data = json.loads(texts.read_text())
clips = data["clips"] if isinstance(data, dict) else data
tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints", use_bf16=True)
for ref in sorted(refs.glob("alt*.wav")):
    d = out / ref.stem
    d.mkdir(parents=True, exist_ok=True)
    for c in clips:
        torch.manual_seed(1234)
        tts.infer(spk_audio_prompt=str(ref), text=c["text"], lang="ES", output_path=str(d / f"{c['id']:04d}.wav"))
    print(ref.stem, "done", flush=True)
