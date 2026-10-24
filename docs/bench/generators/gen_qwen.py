"""Generate the test sentences with Qwen3-TTS 1.7B Base (voice clone, ICL mode)."""
import json
import time
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

HERE = Path(__file__).parent
AUDIO = HERE.parent / "audio"
cfg = json.loads((HERE.parent / "sentences.json").read_text())
NAME = "qwen3"

t0 = time.monotonic()
model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0",
                                      dtype=torch.bfloat16, attn_implementation="sdpa")
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)

stats = {"load_s": round(load_s, 1), "clips": []}
torch.cuda.reset_peak_memory_stats()
for vid, sents in cfg["sentences"].items():
    for ref in (vid, "fixed_es"):
        prompt = model.create_voice_clone_prompt(ref_audio=str(AUDIO / "refs" / f"{ref}.wav"),
                                                 ref_text=(AUDIO / "refs" / f"{ref}.txt").read_text())
        out = AUDIO / "out" / NAME / f"{vid}__{ref}"
        out.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(sents):
            torch.manual_seed(1234)
            torch.cuda.synchronize()
            t0 = time.monotonic()
            wavs, sr = model.generate_voice_clone(text=text, language="Spanish", voice_clone_prompt=prompt)
            torch.cuda.synchronize()
            dt = time.monotonic() - t0
            sf.write(out / f"{i}.wav", wavs[0], sr)
            stats["clips"].append({"dir": out.name, "i": i, "gen_s": round(dt, 2), "audio_s": round(len(wavs[0]) / sr, 2)})
            print(stats["clips"][-1], flush=True)
stats["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
(AUDIO / "out" / NAME / "stats.json").write_text(json.dumps(stats, indent=2))
print("peak", stats["peak_vram_gb"])
