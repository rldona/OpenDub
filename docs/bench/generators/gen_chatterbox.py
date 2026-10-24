"""Generate the test sentences with Chatterbox Multilingual: V3 or the es-ES finetune.

Usage: gen_chatterbox.py v3|es_es
"""
import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
from huggingface_hub import hf_hub_download
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

HERE = Path(__file__).parent
AUDIO = HERE.parent / "audio"
cfg = json.loads((HERE.parent / "sentences.json").read_text())
variant = sys.argv[1]
NAME = f"chatterbox_{variant}"


def es_es_dir() -> Path:
    """Local checkpoint dir: base voice encoder + es-ES T3, S3Gen v3 and tokenizer."""
    d = AUDIO / "ckpt_es_es"
    d.mkdir(exist_ok=True)
    files = {
        "ve.pt": ("ResembleAI/chatterbox", "ve.pt"),
        "conds.pt": ("ResembleAI/chatterbox", "conds.pt"),
        "Cangjie5_TC.json": ("ResembleAI/chatterbox", "Cangjie5_TC.json"),
        "t3_es_es.safetensors": ("ResembleAI/Chatterbox-Multilingual-es-es", "t3_es_es.safetensors"),
        "grapheme_mtl_merged_expanded_v1.json": ("ResembleAI/Chatterbox-Multilingual-es-es",
                                                 "grapheme_mtl_merged_expanded_v1.json"),
    }
    for local, (repo, name) in files.items():
        if not (d / local).exists():
            (d / local).symlink_to(hf_hub_download(repo, name))
    if not (d / "s3gen.pt").exists():
        # s3gen_v3.pt omits the tokenizer's mel filter buffers, which are rebuilt at init
        from chatterbox.models.s3gen import S3Gen
        state = torch.load(hf_hub_download("ResembleAI/Chatterbox-Multilingual-es-es", "s3gen_v3.pt"),
                           map_location="cpu", weights_only=True)
        fresh = S3Gen().state_dict()
        missing, unexpected = set(fresh) - set(state), set(state) - set(fresh)
        print("s3gen_v3 missing", sorted(missing), "unexpected", sorted(unexpected), flush=True)
        assert not unexpected and missing <= {"tokenizer._mel_filters", "tokenizer.window"}
        state |= {k: fresh[k] for k in missing}
        torch.save(state, d / "s3gen.pt")
    return d


t0 = time.monotonic()
if variant == "v3":
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
else:
    model = ChatterboxMultilingualTTS.from_local(es_es_dir(), device="cuda", t3_model="t3_es_es.safetensors")
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)

stats = {"load_s": round(load_s, 1), "clips": []}
torch.cuda.reset_peak_memory_stats()
for vid, sents in cfg["sentences"].items():
    for ref in (vid, "fixed_es"):
        out = AUDIO / "out" / NAME / f"{vid}__{ref}"
        out.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(sents):
            torch.manual_seed(1234)
            torch.cuda.synchronize()
            t0 = time.monotonic()
            wav = model.generate(text, language_id="es", audio_prompt_path=str(AUDIO / "refs" / f"{ref}.wav"))
            torch.cuda.synchronize()
            dt = time.monotonic() - t0
            audio = wav.squeeze(0).cpu().numpy()
            sf.write(out / f"{i}.wav", audio, model.sr)
            stats["clips"].append({"dir": out.name, "i": i, "gen_s": round(dt, 2), "audio_s": round(len(audio) / model.sr, 2)})
            print(stats["clips"][-1], flush=True)
stats["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
(AUDIO / "out" / NAME / "stats.json").write_text(json.dumps(stats, indent=2))
print("peak", stats["peak_vram_gb"])
