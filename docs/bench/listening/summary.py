"""Add up the blind listening sessions (results/*.json, written by session.py serve).

    uv run python docs/bench/listening/summary.py [name …]

Per session and source (engine, version or another tool): the mean note of each
criterion (one overall note, or naturalness, meaning and sync in earlier sessions)
and how often it was preferred. Only fragments with their answer revealed count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
CRITERIA = ("naturalness", "meaning", "sync")


def summarize(data: dict) -> dict:
    revealed = data.get("revealed") or {}
    engines = tuple(data.get("sources") or (data["a"], data["b"]))  # sessions with two dubs had "a" and "b"
    criteria = tuple(data.get("criteria") or CRITERIA)  # an overall note, or the three of earlier sessions
    notes = {e: {c: [] for c in criteria} for e in engines}
    prefer = {e: 0 for e in (*engines, "same")}
    for answer in revealed.values():
        for engine, ratings in answer["ratings"].items():
            for c in criteria:
                notes[engine][c].append(ratings[c])
        prefer[answer["prefer"]] = prefer.get(answer["prefer"], 0) + 1
    means = {e: {c: round(sum(v) / len(v), 2) if v else None for c, v in notes[e].items()} for e in engines}
    return {"name": data["name"], "fragments": len(revealed), "means": means, "prefer": prefer}


def main() -> None:
    names = sys.argv[1:] or [p.stem for p in sorted(RESULTS.glob("*.json"))]
    for name in names:
        s = summarize(json.loads((RESULTS / f"{name}.json").read_text()))
        print(f"{s['name']}: {s['fragments']} fragments answered")
        for engine, means in s["means"].items():
            notes = " · ".join(f"{c} {v if v is not None else '—'}" for c, v in means.items())
            print(f"  {engine:16} {notes} · preferred {s['prefer'][engine]}")
        print(f"  {'same':16} {s['prefer']['same']}")


if __name__ == "__main__":
    main()
