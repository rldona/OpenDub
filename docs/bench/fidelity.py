"""How faithful the translation is: each sentence judged against its original by another model.

    uv run python docs/bench/fidelity.py 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo KS837a-TFRc R4zlpwwEpnY
    uv run python docs/bench/fidelity.py … --file translation.ollama.json --translator qwen3:30b-a3b

The translation is the one the dub speaks (work/<id>/translation.json, or --file): made to
fit each sentence's slot, so what it leaves out to fit counts against it, as it does for
the listener. Hand-edited sentences are skipped. A model other than the translator (Opus
judges Sonnet's translations; say so if it ever judges its own) rates each one with a
fixed rubric, the sentence before it given as context:

- meaning: "kept" (says the same, only wording differs), "nuanced" (a detail, an
  example or a nuance went, the point stays) or "lost" (the meaning changed, it is
  wrong, or something the listener needs is missing);
- terms: "ok", "wrong" (a technical term mistranslated, or translated where it should
  stay as is) or "none" (no technical term in it).

Short videos are judged whole; longer ones on SAMPLE sentences drawn with a fixed seed.
Writes docs/bench/results/fidelity.json (per translator and video, every verdict and its
reason, without the sentences, which stay in work/_bench/fidelity_items.json) and prints
the proportions. It measures only: T-28 sets a local model against Sonnet with it.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

WORK = Path("work")
RESULTS = Path(__file__).parent / "results"
LOCAL = WORK / "_bench"
JUDGE = "claude-opus-5-5"
BATCH = 20
SAMPLE = 60
SEED = 1

SYSTEM = """\
You review the Spanish translation of a video's sentences, as heard in a dub. Each item has \
the original sentence, the one before it (context only) and the Spanish translation that was \
spoken. The translation had to fit the time the original takes, so it may be more concise: \
conciseness alone is not a fault.

Rate each item:
- "meaning": "kept" if it says the same thing (only wording, filler or redundancy differs); \
"nuanced" if a detail, an example or a nuance is missing but the point stays; "lost" if the \
meaning changed, it is wrong, or something the listener needs is missing.
- "terms": "ok" if its technical terms are right; "wrong" if a technical term is \
mistranslated, or translated where Spanish speakers keep the original word; "none" if it has \
no technical term.

Give a reason of at most 12 words, in English.
"""

SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "meaning": {"type": "string", "enum": ["kept", "nuanced", "lost"]},
                       "terms": {"type": "string", "enum": ["ok", "wrong", "none"]},
                       "reason": {"type": "string"}},
        "required": ["id", "meaning", "terms", "reason"], "additionalProperties": False}}},
    "required": ["verdicts"], "additionalProperties": False,
}


def sentences(vid: str, file: str, sample: int) -> list[dict]:
    """The sentences of one video to judge: all of them, or `sample` drawn with SEED."""
    wd = WORK / vid
    originals = json.loads((wd / "segments.json").read_text(encoding="utf-8"))
    spoken = {s["id"]: s["text"] for s in json.loads((wd / file).read_text(encoding="utf-8"))}
    edits = wd / "translation_edits.json"
    edited = {int(k) for k in json.loads(edits.read_text())} if edits.exists() else set()
    items = []
    for i, s in enumerate(originals):
        if s["id"] in edited or not spoken.get(s["id"], "").strip():
            continue
        items.append({"id": f"{vid}#{s['id']}", "video": vid, "original": s["text"],
                      "before": originals[i - 1]["text"] if i else "", "spoken": spoken[s["id"]]})
    if len(items) > sample:
        items = sorted(random.Random(SEED).sample(items, sample), key=lambda x: int(x["id"].split("#")[1]))
    return items


def judge(items: list[dict]) -> dict[str, dict]:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    payload = [{"id": i["id"], "before": i["before"], "original": i["original"], "translation": i["spoken"]}
               for i in items]
    out = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", JUDGE, "--system-prompt", SYSTEM,
         "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence", "--setting-sources", ""],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=900,
    )
    data = json.loads(out.stdout)
    if data.get("is_error") or not data.get("structured_output"):
        raise SystemExit(f"claude failed: {data.get('result')}")
    return {v["id"]: v for v in data["structured_output"]["verdicts"]}


def share(counts: Counter, key: str) -> float | None:
    total = sum(counts.values())
    return round(counts[key] / total, 3) if total else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--file", default="translation.json", help="the translation to judge, in each work/<id>/")
    parser.add_argument("--translator", default="claude-sonnet-5-5", help="who made it (a label for the results)")
    parser.add_argument("--sample", type=int, default=SAMPLE, help="sentences per video beyond which it samples")
    args = parser.parse_args()
    if args.translator == JUDGE:
        print(f"note: {JUDGE} is judging its own translation")
    items = [i for vid in args.videos for i in sentences(vid, args.file, args.sample)]
    print(f"{len(items)} sentences from {len(args.videos)} videos, judged by {JUDGE}")
    for start in range(0, len(items), BATCH):
        batch = items[start: start + BATCH]
        verdicts = judge(batch)
        missing = [i for i in batch if i["id"] not in verdicts]
        if missing:  # asked once more, alone
            verdicts |= judge(missing)
        for i in batch:
            v = verdicts.get(i["id"], {"meaning": None, "terms": None, "reason": "no verdict"})
            i["meaning"], i["terms"], i["reason"] = v["meaning"], v["terms"], v["reason"]
    per_video: dict[str, dict[str, Counter]] = defaultdict(lambda: {"meaning": Counter(), "terms": Counter()})
    for i in items:
        per_video[i["video"]]["meaning"][i["meaning"]] += 1
        per_video[i["video"]]["terms"][i["terms"]] += 1
    every = {"meaning": sum((c["meaning"] for c in per_video.values()), Counter()),
             "terms": sum((c["terms"] for c in per_video.values()), Counter())}

    def summary(c: dict[str, Counter]) -> dict:
        with_terms = c["terms"]["ok"] + c["terms"]["wrong"]
        return {"judged": sum(c["meaning"].values()), **{k: c["meaning"][k] for k in ("kept", "nuanced", "lost")},
                "lost_share": share(c["meaning"], "lost"), "nuanced_share": share(c["meaning"], "nuanced"),
                "with_terms": with_terms, "terms_wrong": c["terms"]["wrong"],
                "terms_wrong_share": round(c["terms"]["wrong"] / with_terms, 3) if with_terms else None}

    path = RESULTS / "fidelity.json"
    RESULTS.mkdir(parents=True, exist_ok=True)
    saved = json.loads(path.read_text()) if path.exists() else {}
    # committed: verdicts without the sentences (third-party videos and their translations stay local)
    saved[args.translator] = {
        "judge": JUDGE, "file": args.file, "sample": args.sample, "seed": SEED,
        "summary": summary(every), "videos": {v: summary(c) for v, c in sorted(per_video.items())},
        "items": [{k: i[k] for k in ("id", "meaning", "terms", "reason")}
                  | {"original_chars": len(i["original"]), "spoken_chars": len(i["spoken"])} for i in items],
    }
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=1))
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / f"fidelity_items.{args.translator.replace(':', '_')}.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1))
    for vid, s in [*saved[args.translator]["videos"].items(), ("all", saved[args.translator]["summary"])]:
        print(f"{vid:14} {s['judged']:3} judged · kept {s['kept']} · nuanced {s['nuanced']} · lost {s['lost']} "
              f"({s['lost_share']:.0%}) · terms wrong {s['terms_wrong']}/{s['with_terms']}")


if __name__ == "__main__":
    main()
