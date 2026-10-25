# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "faster-whisper>=1.2.1",
#     "librosa>=0.11",
#     "numpy",
#     "resemblyzer>=0.1.4",
#     "speechbrain>=1.1.2",
#     "torch>=2.7",
#     "torchaudio>=2.7",
# ]
# [tool.uv.sources]
# torch = [{ index = "pytorch-cu128" }]
# torchaudio = [{ index = "pytorch-cu128" }]
# [[tool.uv.index]]
# name = "pytorch-cu128"
# url = "https://download.pytorch.org/whl/cu128"
# explicit = true
# ///
"""Score a voice model's clips against every model benchmarked so far, in one command.

    uv run docs/bench/run.py <name>          # score audio/out/<name> (and audio/fit/<name>)
    uv run docs/bench/run.py --all           # rescore every model that has clips
    uv run docs/bench/run.py --refs <dir>    # tremor of one speaker's alternative references
    uv run docs/bench/run.py --dub <dir>…    # real dubs: folders with tts.json and its clips
    uv run docs/bench/run.py --compare <name>…  # one markdown table per video, from results/

A new model only has to write its clips where the generators in generators/
write theirs (see README.md). Scores go to results/<name>.json, which is
committed, so the comparison table includes models whose clips are no longer
on disk. The dependencies above are installed by uv on the first run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402

AUDIO = HERE / "audio"  # gitignored: reference cuts and generated voices
RESULTS = HERE / "results"
CFG = json.loads((HERE / "sentences.json").read_text())
# same speaker, another stretch of the video: the similarity ceiling
OTHER = {"17kBVfGjI8c": (38.4, 56.2), "rwF-X5STYks": (42.0, 58.8)}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def ref_embeddings() -> dict:
    refs = {r: metrics.load16k(AUDIO / "refs" / f"{r}.wav") for r in [*CFG["refs"], "fixed_es"]}
    return {r: metrics.embed(a, AUDIO) for r, a in refs.items()}


def score_sentences(name: str, refs: dict) -> dict:
    """(A) the 12 test sentences, per reference type: own video's speaker or the fixed Spanish one."""
    out = {}
    for ref_type in ("own", "fixed_es"):
        rows = []
        for vid, sents in CFG["sentences"].items():
            ref = vid if ref_type == "own" else "fixed_es"
            d = AUDIO / "out" / name / f"{vid}__{ref}"
            if not d.exists() and ref_type == "own":
                d = AUDIO / "out" / name / f"{vid}__none"  # engines without cloning (edge-tts baseline)
            if not d.exists():
                continue
            audios = []
            for i, text in enumerate(sents):
                audio = metrics.load16k(d / f"{i}.wav")
                audios.append(audio)
                e = metrics.embed(audio, AUDIO)
                rows.append({"vid": vid, "i": i, "cps": round(len(text) / (len(audio) / metrics.SR), 1),
                             **metrics.intelligibility(audio, text),
                             "sim_original": metrics.similarity(e, refs[vid]),
                             "sim_fixed_es": metrics.similarity(e, refs["fixed_es"])})
            if ref_type == "own":
                out.setdefault("stability", {})[vid] = metrics.voice_stability(audios)
        if rows:
            out[ref_type] = {
                "cer": mean(r["cer"] for r in rows), "worst_cer": max(r["cer"] for r in rows),
                "p_es": mean(r["p_es"] for r in rows), "cps": mean(r["cps"] for r in rows),
                "ecapa_original": mean(r["sim_original"]["ecapa"] for r in rows),
                "ecapa_fixed_es": mean(r["sim_fixed_es"]["ecapa"] for r in rows),
                "resemblyzer_original": mean(r["sim_original"]["resemblyzer"] for r in rows),
                "clips": rows,
            }
    stats = AUDIO / "out" / name / "stats.json"
    if stats.exists():
        s = json.loads(stats.read_text())
        out["speed"] = {"load_s": s["load_s"], "peak_vram_gb": s.get("peak_vram_gb"),
                        "rtf": round(sum(c["gen_s"] for c in s["clips"]) / sum(c["audio_s"] for c in s["clips"]), 2)}
    return out


def score_fit(name: str) -> dict | None:
    """(B) the real dub segments with their slots: how many fit without atempo, and how they sound."""
    d = AUDIO / "fit" / name
    if not (d / "fit.json").exists():
        return None
    rows = json.loads((d / "fit.json").read_text())
    out = {"clips": len(rows), "fit_without_atempo": sum(r["fits"] for r in rows), "per_video": {}}
    for vid in sorted({r["vid"] for r in rows}):
        ref = metrics.embed(metrics.load16k(AUDIO / "fit" / f"{vid}_clone_ref.wav"), AUDIO)
        audios, scores = [], []
        for r in (r for r in rows if r["vid"] == vid):
            audio = metrics.load16k(d / vid / r["final"])
            audios.append(audio)
            scores.append({**metrics.intelligibility(audio, r["text"]),
                           "ecapa": metrics.similarity(metrics.embed(audio, AUDIO), ref)["ecapa"]})
        out["per_video"][vid] = {"cer": mean(s["cer"] for s in scores), "p_es": mean(s["p_es"] for s in scores),
                                 "ecapa": mean(s["ecapa"] for s in scores), **metrics.voice_stability(audios)}
    return out


def score(name: str) -> dict:
    print(f"Scoring {name}…", flush=True)
    result = {"model": name, "sentences": score_sentences(name, ref_embeddings())}
    if (fit := score_fit(name)) is not None:
        result["fit"] = fit
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def baselines() -> None:
    """The ceiling (same speaker elsewhere in the video) and each reference's own stability."""
    refs = ref_embeddings()
    out = {}
    for vid, (ss, to) in OTHER.items():
        audio = metrics.load16k(AUDIO / "vocals" / f"{vid}.wav", ss, to) if (AUDIO / "vocals" / f"{vid}.wav").exists() else None
        out[vid] = {"same_speaker_ecapa": metrics.similarity(metrics.embed(audio, AUDIO), refs[vid])["ecapa"]
                    if audio is not None else None,
                    "reference": metrics.voice_stability([metrics.load16k(AUDIO / "refs" / f"{vid}.wav")])}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "_baselines.json").write_text(json.dumps(out, indent=1))


def table() -> None:
    rows = [json.loads(p.read_text()) for p in sorted(RESULTS.glob("*.json")) if not p.name.startswith("_")]
    print(f"\n{'model':18} {'cer':>6} {'p_es':>6} {'ecapa':>6} {'cps':>5} {'rtf':>5} {'vram':>5} │ "
          f"{'tremor pitch/loud (male · female)':>36} │ fit")
    for r in rows:
        own = r["sentences"].get("own", {})
        sp = r["sentences"].get("speed", {})
        st = r["sentences"].get("stability", {})
        trem = " · ".join(f"{s['pitch_tremor']}/{s['loudness_tremor']}" for s in st.values())
        fit = f"{r['fit']['fit_without_atempo']}/{r['fit']['clips']}" if "fit" in r else "—"
        print(f"{r['model']:18} {own.get('cer', '—'):>6} {own.get('p_es', '—'):>6} {own.get('ecapa_original', '—'):>6} "
              f"{own.get('cps', '—'):>5} {sp.get('rtf', '—'):>5} {sp.get('peak_vram_gb', '—'):>5} │ {trem:>36} │ {fit}")


def fit_counts(name: str, floor: float) -> dict:
    """Per video: clips that fit their slot without atempo, and those that did with a factor >= floor."""
    path = AUDIO / "fit" / name / "fit.json"
    if not path.exists():
        return {}
    out = {}
    for r in json.loads(path.read_text()):
        c = out.setdefault(r["vid"], {"clips": 0, "fit": 0, "fit_floor": 0, "native": False})
        c["clips"] += 1
        c["fit"] += r["fits"]
        factors = r.get("factors", [1.0])  # engines without a native speed control have none
        c["fit_floor"] += r["fits"] and factors[-1] >= floor
        c["native"] |= len(factors) > 1
    return out


def compare(names: list[str], floor: float = 0.7) -> None:
    """The comparison table, one per video: test sentences (A) from that video's speaker, dub fit (B)."""
    base = json.loads((RESULTS / "_baselines.json").read_text())
    for vid in CFG["sentences"]:
        print(f"\n### {vid}\n")
        print("| engine | CER | p_es | ECAPA | tremor pitch/loud | chars/s | RTF | VRAM GB | fit without atempo "
              f"| fit with factor ≥ {floor} |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        ref = base[vid]
        print(f"| *original speaker* | | | {ref['same_speaker_ecapa']} | "
              f"{ref['reference']['pitch_tremor']}/{ref['reference']['loudness_tremor']} | | | | | |")
        for name in names:
            r = json.loads((RESULTS / f"{name}.json").read_text())
            clips = [c for c in r["sentences"]["own"]["clips"] if c["vid"] == vid]
            st = r["sentences"]["stability"][vid]
            sp = r["sentences"]["speed"]
            fc = fit_counts(name, floor).get(vid)
            fit = f"{fc['fit']}/{fc['clips']}" if fc else "—"
            floor_fit = f"{fc['fit_floor']}/{fc['clips']}" if fc and fc["native"] else "—"
            print(f"| {name} | {mean(c['cer'] for c in clips)} | {mean(c['p_es'] for c in clips)} "
                  f"| {mean(c['sim_original']['ecapa'] for c in clips)} | {st['pitch_tremor']}/{st['loudness_tremor']} "
                  f"| {mean(c['cps'] for c in clips)} | {sp.get('rtf', '—')} | {sp.get('peak_vram_gb', '—')} "
                  f"| {fit} | {floor_fit} |")
        print(f"\nDub segments of {vid} as fitted (B):\n")
        print("| engine | CER | p_es | ECAPA | tremor pitch/loud |")
        print("|---|---|---|---|---|")
        for name in names:
            r = json.loads((RESULTS / f"{name}.json").read_text())
            if (f := r.get("fit", {}).get("per_video", {}).get(vid)):
                print(f"| {name} | {f['cer']} | {f['p_es']} | {f['ecapa']} | {f['pitch_tremor']}/{f['loudness_tremor']} |")


def score_refs(refs_dir: Path) -> None:
    """Tremor of the clips generated from each alternative reference (generators/gen_alt_refs.py)."""
    out = {}
    for d in sorted(p for p in refs_dir.iterdir() if p.is_dir()):
        ref = refs_dir.parent / "alt_refs" / f"{d.name}.wav"
        out[d.name] = {"reference": metrics.voice_stability([metrics.load16k(ref)]) if ref.exists() else None,
                       "clips": metrics.voice_stability([metrics.load16k(p) for p in sorted(d.glob("*.wav"))])}
        print(d.name, out[d.name], flush=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"_refs_{refs_dir.name}.json").write_text(json.dumps(out, indent=1))


def score_dubs(dirs: list[Path]) -> None:
    """Real dubs (a work/<video> folder or a copy of its tts.json and clips), one row per folder.

    Similarity is measured against a fixed stretch of the original speaker that
    no reference uses (OTHER), so dubs made from different references compare fairly.
    """
    rows = []
    for d in dirs:
        data = json.loads((d / "tts.json").read_text())
        clips = data["clips"] if isinstance(data, dict) else data
        vid = next(v for v in OTHER if v in str(d))
        original = metrics.embed(metrics.load16k(AUDIO / "vocals" / f"{vid}.wav", *OTHER[vid]), AUDIO)
        audios, scores = [], []
        for c in clips:
            path = d / c["file"] if (d / c["file"]).exists() else d / Path(c["file"]).name
            audio = metrics.load16k(path)
            audios.append(audio)
            scores.append({**metrics.intelligibility(audio, c["text"]),
                           "ecapa": metrics.similarity(metrics.embed(audio, AUDIO), original)["ecapa"]})
        row = {"dub": str(d.relative_to(HERE) if d.is_relative_to(HERE) else d),
               "engine": data.get("engine") if isinstance(data, dict) else None,
               "reference_f0_hz": data.get("reference_f0_hz") if isinstance(data, dict) else None,
               "clips": len(clips), "atempo": sum(c["tempo"] > 1.0 for c in clips),
               "min_factor": min(c.get("factor", 1.0) for c in clips),
               "cer": mean(s["cer"] for s in scores), "p_es": mean(s["p_es"] for s in scores),
               "ecapa_original": mean(s["ecapa"] for s in scores), **metrics.voice_stability(audios)}
        rows.append(row)
        print(row, flush=True)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "_dubs.json").write_text(json.dumps(rows, indent=1))
    print(f"\n{'dub':52} {'cer':>6} {'p_es':>6} {'ecapa':>6} {'tremor p/l':>12} {'atempo':>6} {'min f':>6}")
    for r in rows:
        print(f"{r['dub'][-52:]:52} {r['cer']:>6} {r['p_es']:>6} {r['ecapa_original']:>6} "
              f"{r['pitch_tremor']}/{r['loudness_tremor']:>5} {r['atempo']:>6} {r['min_factor']:>6}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("name", nargs="?", help="model folder under audio/out (and audio/fit)")
    ap.add_argument("--all", action="store_true", help="rescore every model with clips on disk")
    ap.add_argument("--refs", type=Path, help="score clips generated from alternative references")
    ap.add_argument("--dub", type=Path, nargs="+", help="score real dubs (folders with tts.json)")
    ap.add_argument("--compare", nargs="+", metavar="NAME", help="one markdown table per video, from results/")
    args = ap.parse_args()
    if args.compare:
        compare(args.compare)
        sys.exit()
    if args.dub:
        score_dubs([d.resolve() for d in args.dub])
    elif args.refs:
        score_refs(args.refs)
    elif args.all:
        baselines()
        for d in sorted(p for p in (AUDIO / "out").iterdir() if p.is_dir()):
            score(d.name)
    elif args.name:
        score(args.name)
    else:
        ap.error("give a model name, --all or --refs")
    if not (args.refs or args.dub):
        table()
