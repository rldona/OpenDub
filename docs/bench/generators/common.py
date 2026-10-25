"""The shared loop of the engine generators, so each one only says how its model speaks.

(A) the 12 test sentences from each video's speaker and from the fixed Spanish
reference, into audio/out/<name>/; (B) the real dub segments with their slots,
into audio/fit/<name>/. With a native speed control, (B) corrects a clip that
overflows its slot as gen_indextts.py does: up to two corrections, factor
(duration multiplier, 1/speed) not below MIN_FACTOR. Without one, (B) only
measures the natural duration.

Standard library, numpy, soundfile and torch only: it runs in each engine's venv.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Callable

import soundfile as sf
import torch

HERE = Path(__file__).resolve().parent
AUDIO = HERE.parent / "audio"
FIT = AUDIO / "fit"
CFG = json.loads((HERE.parent / "sentences.json").read_text())
SEGMENTS = FIT / "indextts" / "fit.json"  # the same 42 dub segments and slots every engine was measured on
TRIM = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse")
MIN_FACTOR = 0.5
SEED = 1234

# synth(text, reference wav, reference transcript, output wav, factor)
Synth = Callable[[str, Path, str, Path, float], None]


def trimmed_duration(path: Path) -> float:
    out = path.with_suffix(".trim.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-af", TRIM, "-ac", "1", "-ar", "24000", str(out)],
                   check=True)
    d = sf.info(str(out)).duration
    out.unlink()
    return d


def timed(synth: Synth, text: str, ref: Path, ref_text: str, out: Path, factor: float = 1.0) -> float:
    torch.manual_seed(SEED)
    torch.cuda.synchronize()
    t = time.monotonic()
    synth(text, ref, ref_text, out, factor)
    torch.cuda.synchronize()
    return time.monotonic() - t


def warm_up(synth: Synth) -> None:
    """CUDA kernels and lazy initialisation: not timed."""
    ref = AUDIO / "refs" / "fixed_es.wav"
    out = AUDIO / "out" / "_warmup.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    for text in ("Esto es una frase de calentamiento.", "Y esta es otra, algo más larga que la primera."):
        synth(text, ref, (AUDIO / "refs" / "fixed_es.txt").read_text().strip(), out, 1.0)
    out.unlink()


def sentences(name: str, synth: Synth, load_s: float, extra: dict | None = None) -> None:
    """(A): audio/out/<name>/<video>__<reference>/<i>.wav and stats.json."""
    stats = {"load_s": round(load_s, 1), "seed": SEED, **(extra or {}), "clips": []}
    torch.cuda.reset_peak_memory_stats()
    for vid, sents in CFG["sentences"].items():
        for ref in (vid, "fixed_es"):
            out = AUDIO / "out" / name / f"{vid}__{ref}"
            out.mkdir(parents=True, exist_ok=True)
            ref_text = (AUDIO / "refs" / f"{ref}.txt").read_text().strip()
            for i, text in enumerate(sents):
                dt = timed(synth, text, AUDIO / "refs" / f"{ref}.wav", ref_text, out / f"{i}.wav")
                stats["clips"].append({"dir": out.name, "i": i, "gen_s": round(dt, 2),
                                       "audio_s": round(sf.info(str(out / f"{i}.wav")).duration, 2)})
                print(stats["clips"][-1], flush=True)
    stats["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    gen = sum(c["gen_s"] for c in stats["clips"])
    audio = sum(c["audio_s"] for c in stats["clips"])
    stats["rtf"] = round(gen / audio, 3)
    (AUDIO / "out" / name / "stats.json").write_text(json.dumps(stats, indent=2))
    print(f"{name}: RTF {stats['rtf']}, peak {stats['peak_vram_gb']} GB", flush=True)


def fit(name: str, synth: Synth, native_speed: bool) -> None:
    """(B): audio/fit/<name>/<video>/<id>.f<n>.wav and fit.json, in gen_indextts.py's format."""
    rows = []
    for c in json.loads(SEGMENTS.read_text()):
        vid, text, slot = c["vid"], c["text"], c["slot"]
        ref = FIT / f"{vid}_clone_ref.wav"
        ref_text = ref.with_suffix(".txt").read_text().strip()
        out = FIT / name / vid
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{c['id']:04d}.f1.wav"
        timed(synth, text, ref, ref_text, path)
        natural = trimmed_duration(path)
        row = {"vid": vid, "id": c["id"], "text": text, "slot": slot, "chars": len(text),
               "natural": round(natural, 3), "factors": [1.0], "durations": [round(natural, 3)]}
        factor, dur = 1.0, natural
        for _ in range(2 if native_speed else 0):
            if dur <= slot:
                break
            factor = max(factor * slot * 0.97 / dur, MIN_FACTOR)
            path = out / f"{c['id']:04d}.f{len(row['factors']) + 1}.wav"
            timed(synth, text, ref, ref_text, path, factor)
            dur = trimmed_duration(path)
            row["factors"].append(round(factor, 3))
            row["durations"].append(round(dur, 3))
        row["final"] = path.name
        row["fits"] = dur <= slot
        rows.append(row)
        print(row, flush=True)
    (FIT / name / "fit.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(f"{name}: {sum(r['fits'] for r in rows)}/{len(rows)} fit without atempo", flush=True)
