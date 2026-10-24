"""IndexTTS-2.5 with its optional accelerations, on the benchmark's test sentences.

Same sentences, references and seed as gen_indextts.py (A), so run.py compares
speed and quality directly. Run with the IndexTTS venv's python, from its repo:

    .venv/bin/python -I <this file> <docs/bench/audio> <name> [accel] [compile] [cuda_kernel] [seed=N]

accel: IndexTTS's GPT2 acceleration engine (flash-attn; `uv sync --extra accel`)
compile: torch.compile on the s2mel stage
cuda_kernel: BigVGAN's fused CUDA kernel (needs nvcc and ninja to build)
"""
import json
import sys
import time
import wave
from pathlib import Path

import torch
from indextts.infer_v2_5 import IndexTTS2

AUDIO = Path(sys.argv[1])
NAME = sys.argv[2]
flags = {a for a in sys.argv[3:] if "=" not in a}
SEED = int(next((a.split("=")[1] for a in sys.argv[3:] if a.startswith("seed=")), 1234))
cfg = json.loads((Path(__file__).parent.parent / "sentences.json").read_text())

t0 = time.monotonic()
tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints", use_bf16=True,
                use_accel="accel" in flags, use_torch_compile="compile" in flags,
                use_cuda_kernel="cuda_kernel" in flags)
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s with {sorted(flags) or 'no accelerations'}", flush=True)

# warm-up (CUDA kernels, torch.compile): not timed
warm = AUDIO / "out" / NAME / "_warmup.wav"
warm.parent.mkdir(parents=True, exist_ok=True)
for text in ("Esto es una frase de calentamiento.", "Y esta es otra, algo más larga que la primera."):
    tts.infer(spk_audio_prompt=str(AUDIO / "refs" / "fixed_es.wav"), text=text, lang="ES", output_path=str(warm))
warm.unlink()

stats = {"load_s": round(load_s, 1), "flags": sorted(flags), "seed": SEED, "clips": []}
torch.cuda.reset_peak_memory_stats()
for vid, sents in cfg["sentences"].items():
    for ref in (vid, "fixed_es"):
        out = AUDIO / "out" / NAME / f"{vid}__{ref}"
        out.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(sents):
            torch.manual_seed(SEED)
            torch.cuda.synchronize()
            t = time.monotonic()
            tts.infer(spk_audio_prompt=str(AUDIO / "refs" / f"{ref}.wav"), text=text, lang="ES",
                      output_path=str(out / f"{i}.wav"))
            torch.cuda.synchronize()
            dt = time.monotonic() - t
            with wave.open(str(out / f"{i}.wav")) as w:
                audio_s = w.getnframes() / w.getframerate()
            stats["clips"].append({"dir": out.name, "i": i, "gen_s": round(dt, 2), "audio_s": round(audio_s, 2)})
stats["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
gen = sum(c["gen_s"] for c in stats["clips"])
audio = sum(c["audio_s"] for c in stats["clips"])
stats["rtf"] = round(gen / audio, 3)
(AUDIO / "out" / NAME / "stats.json").write_text(json.dumps(stats, indent=2))
print(f"{NAME}: {len(stats['clips'])} clips, {gen:.1f}s for {audio:.1f}s of audio → RTF {stats['rtf']}, "
      f"peak {stats['peak_vram_gb']} GB", flush=True)
