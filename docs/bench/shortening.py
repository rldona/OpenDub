"""How much meaning the shortening loses: each shortened sentence judged against its full translation.

    uv run python docs/bench/shortening.py KS837a-TFRc h7PA4mXE_GA 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo

A sentence is shortened when what a version's clip says differs from the translation
it was made from (its tts.json "sources") and the sentence wasn't edited by hand.
Versions older than "sources" are skipped: set against the current translation, a
sentence translated again since would count as shortened. Claude (the same
CLI as the translation) judges each one with a fixed rubric:

- kept: the shorter sentence says the same; only wording or redundancy went;
- nuanced: a detail, an example or a nuance went, the point stays;
- lost: the meaning changed, or something the listener needs went.

Writes docs/bench/results/shortening.json (per engine, every verdict and its reason, without
the sentences, which stay in work/_bench/shortening_items.json) and prints the proportions. It measures only: any change to the shortening prompt is to
be decided with these figures.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

WORK = Path("work")
RESULTS = Path(__file__).parent / "results"
LOCAL = WORK / "_bench"  # the sentences themselves, not committed
MODEL = "claude-sonnet-5-5"
BATCH = 20
VERSION = re.compile(r"(\d{8}-\d{6}-)?([a-z][a-z-]*)")

SYSTEM = """\
You review a Spanish dub. Each item has the original sentence (another language), its full \
Spanish translation, and a shorter version that was spoken instead so it would fit its time slot.

Judge the shorter version against the full translation, with this rubric:
- "kept": it says the same thing; only wording, filler or redundancy was removed.
- "nuanced": a detail, an example or a nuance is missing, but the point stays.
- "lost": the meaning changed, it is wrong, or something the listener needs is missing.

Return one verdict per item id, with a reason of at most 12 words, in English.
"""

SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "verdict": {"type": "string", "enum": ["kept", "nuanced", "lost"]},
                       "reason": {"type": "string"}},
        "required": ["id", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["verdicts"], "additionalProperties": False,
}


def shortened(vid: str) -> list[dict]:
    """Every shortened sentence of every kept version of a video, once per distinct shorter text."""
    wd = WORK / vid
    originals = {s["id"]: s["text"] for s in json.loads((wd / "segments.json").read_text(encoding="utf-8"))}
    edits = wd / "translation_edits.json"
    edited = {int(k) for k in json.loads(edits.read_text())} if edits.exists() else set()
    found, seen = [], set()
    for index_path in sorted((wd / "outputs").glob("*.tts.json")):
        if not (m := VERSION.fullmatch(index_path.name.removesuffix(".tts.json"))):
            continue
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(index, dict) or not index.get("sources"):
            continue
        sources = {int(k): v for k, v in index["sources"].items()}
        for c in index["clips"]:
            full = sources.get(c["id"])
            if not full or c["id"] in edited or c["text"].strip() == full.strip() or c.get("voice") == "edge":
                continue
            key = (c["id"], c["text"])
            if key in seen:
                continue
            seen.add(key)
            found.append({"id": f"{vid}#{c['id']}#{len(found)}", "video": vid, "engine": index.get("engine") or m[2],
                          "original": originals.get(c["id"], ""), "full": full, "shortened": c["text"]})
    return found


def judge(items: list[dict]) -> dict[str, dict]:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    payload = [{"id": i["id"], "original": i["original"], "full": i["full"], "shorter": i["shortened"]} for i in items]
    out = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", MODEL, "--system-prompt", SYSTEM,
         "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence", "--setting-sources", ""],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, timeout=600,
    )
    data = json.loads(out.stdout)
    if data.get("is_error") or not data.get("structured_output"):
        raise SystemExit(f"claude failed: {data.get('result')}")
    return {v["id"]: v for v in data["structured_output"]["verdicts"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+")
    args = parser.parse_args()
    items = [i for vid in args.videos for i in shortened(vid)]
    print(f"{len(items)} shortened sentences")
    for start in range(0, len(items), BATCH):
        batch = items[start : start + BATCH]
        verdicts = judge(batch)
        for i in batch:
            v = verdicts.get(i["id"], {"verdict": None, "reason": "no verdict"})
            i["verdict"], i["reason"] = v["verdict"], v["reason"]
    per_engine: dict[str, Counter] = defaultdict(Counter)
    for i in items:
        per_engine[i["engine"]][i["verdict"]] += 1
    summary = {e: {**dict(c), "total": sum(c.values()),
                   "lost_share": round(c["lost"] / sum(c.values()), 3) if sum(c.values()) else None}
               for e, c in sorted(per_engine.items())}
    RESULTS.mkdir(parents=True, exist_ok=True)
    # committed: verdicts without the sentences (third-party videos and their translations stay local)
    public = [{k: i[k] for k in ("id", "video", "engine", "verdict", "reason")}
              | {"full_chars": len(i["full"]), "short_chars": len(i["shortened"])} for i in items]
    (RESULTS / "shortening.json").write_text(json.dumps({"model": MODEL, "summary": summary, "items": public},
                                                        ensure_ascii=False, indent=1))
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "shortening_items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    for engine, s in summary.items():
        print(f"{engine:14} {s['total']:3} shortened · kept {s.get('kept', 0)} · nuanced {s.get('nuanced', 0)} · "
              f"lost {s.get('lost', 0)} ({s['lost_share']:.0%})")


if __name__ == "__main__":
    main()
