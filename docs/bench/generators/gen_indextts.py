"""IndexTTS-2.5: (A) the same 12 test sentences and references as the other candidates;
(B) the real dub segments, fitted to their slots with duration_factor instead of atempo.

Run with the IndexTTS venv's python, from the IndexTTS repo (checkpoints/ is relative):
    cd <indextts>/repo && .venv/bin/python -I <this file> <docs/bench/audio>
"""
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import torch
from indextts.infer_v2_5 import IndexTTS2

CLONE = Path(sys.argv[1])  # docs/bench/audio
FIT = CLONE / "fit"
cfg = json.loads((Path(__file__).parent.parent / "sentences.json").read_text())
TRIM = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse")
MIN_FACTOR = 0.5  # IndexTTS's documented lower bound


def trimmed_duration(path: Path) -> float:
    out = path.with_suffix(".trim.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-af", TRIM, "-ac", "1", "-ar", "24000", str(out)],
                   check=True)
    with wave.open(str(out)) as w:
        d = w.getnframes() / w.getframerate()
    out.unlink()
    return d


t0 = time.monotonic()
tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints", use_bf16=True)
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)


def gen(text: str, ref: Path, out: Path, factor: float = 1.0) -> float:
    torch.manual_seed(1234)
    torch.cuda.synchronize()
    t = time.monotonic()
    tts.infer(spk_audio_prompt=str(ref), text=text, lang="ES", output_path=str(out), duration_factor=factor)
    torch.cuda.synchronize()
    return time.monotonic() - t


# (A) same sentences and references as the other candidates
stats = {"load_s": round(load_s, 1), "clips": []}
torch.cuda.reset_peak_memory_stats()
for vid, sents in cfg["sentences"].items():
    for ref in (vid, "fixed_es"):
        out = CLONE / "out" / "indextts" / f"{vid}__{ref}"
        out.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(sents):
            dt = gen(text, CLONE / "refs" / f"{ref}.wav", out / f"{i}.wav")
            with wave.open(str(out / f"{i}.wav")) as w:
                audio_s = w.getnframes() / w.getframerate()
            stats["clips"].append({"dir": out.name, "i": i, "gen_s": round(dt, 2), "audio_s": round(audio_s, 2)})
            print(stats["clips"][-1], flush=True)
stats["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
(CLONE / "out" / "indextts" / "stats.json").write_text(json.dumps(stats, indent=2))

# (B) real dub segments: natural duration, then up to two duration_factor corrections
rows = []
for vid in ("17kBVfGjI8c", "rwF-X5STYks"):
    ref = FIT / f"{vid}_clone_ref.wav"
    base = json.loads((FIT / "chatterbox" / vid / "tts.json").read_text())
    out = FIT / "indextts" / vid
    out.mkdir(parents=True, exist_ok=True)
    for c in base:
        text, slot = c["text"], c["slot"]
        path = out / f"{c['id']:04d}.f1.wav"
        gen(text, ref, path)
        natural = trimmed_duration(path)
        row = {"vid": vid, "id": c["id"], "text": text, "slot": slot, "chars": len(text), "natural": round(natural, 3),
               "factors": [1.0], "durations": [round(natural, 3)], "chatterbox_raw": c["raw_duration"],
               "chatterbox_tempo": c["tempo"]}
        factor, dur = 1.0, natural
        for _ in range(2):
            if dur <= slot:
                break
            factor = max(factor * slot * 0.97 / dur, MIN_FACTOR)
            path = out / f"{c['id']:04d}.f{len(row['factors']) + 1}.wav"
            gen(text, ref, path, factor)
            dur = trimmed_duration(path)
            row["factors"].append(round(factor, 3))
            row["durations"].append(round(dur, 3))
        row["final"] = path.name
        row["fits"] = dur <= slot
        rows.append(row)
        print(row, flush=True)
(FIT / "indextts" / "fit.json").write_text(json.dumps(rows, indent=1))
print("peak", round(torch.cuda.max_memory_allocated() / 2**30, 2))
