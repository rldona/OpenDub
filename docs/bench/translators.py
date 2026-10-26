"""Translate the corpus with Claude and with local models (Ollama), same prompt and budget, and compare.

    uv run python docs/bench/translators.py 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo KS837a-TFRc R4zlpwwEpnY \\
        --translator cli:claude-sonnet-5-5 --translator ollama:gemma3:27b --translator ollama:qwen3.6:35b-a3b-coding

T-28. Each translator gets exactly what a dub gives it: the video's sentences in blocks
of 30, the previous context, and each sentence's character budget at the pace of the
voice that would speak it (Chatterbox V3, its calibrated rate from work/voice_rates.json;
several voices for a video diarized into several). It runs translate.run itself, on a
copy of the video's folder under work/_bench/translators/<translator>/ (links to the
video's files, so its own translation and hand edits are never touched), and copies the
result to work/<id>/translation.<label>.json for fidelity.py --file.

Per video and translator, into docs/bench/results/translators.json:
- time (wall clock, the model's load included) and whether it failed;
- the Spanish/original length ratio;
- sentences over their budget (max_chars) and over 1.25 times it: what the voice phase
  would have to speed up or shorten.

Fidelity is judged afterwards with fidelity.py on each translation.<label>.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from opendub import translate, voices  # noqa: E402
from opendub.config import Settings  # noqa: E402
from opendub.models import load_segments  # noqa: E402
from opendub.tts import Pace, voice_rate  # noqa: E402
from opendub.workdir import WorkDir  # noqa: E402

WORK = Path("work")
BENCH = WORK / "_bench" / "translators"
RESULTS = Path(__file__).parent / "results" / "translators.json"
OWN = {"translation.json", "translation.style.json", "translation_edits.json", "translate_blocks", "manifest.json"}


def label(translator: str) -> str:
    return translator.replace(":", "_").replace("/", "_")


def settings_for(translator: str, root: Path, several: bool) -> Settings:
    backend, _, model = translator.partition(":")
    base = Settings(work_root=root, backend=backend, tts="clone", engine="chatterbox", multi_speaker=several)
    return replace(base, ollama_model=model) if backend == "ollama" else replace(base, claude_model=model)


def copy_of(vid: str, root: Path) -> WorkDir:
    """The video's folder under `root`, its files linked, without its translation."""
    src, dst = (WORK / vid).resolve(), root / vid
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if f.name not in OWN:
            (dst / f.name).symlink_to(f)
    manifest = json.loads((src / "manifest.json").read_text())
    (dst / "manifest.json").write_text(json.dumps({k: v for k, v in manifest.items() if k != "translate"}))
    shutil.copy(WORK / "voice_rates.json", root / "voice_rates.json")
    return WorkDir(root, vid)


def budgets(wd: WorkDir, settings: Settings) -> tuple[list, dict[int, int]]:
    """The segments and each one's max_chars, as translate.run computes them."""
    segments = load_segments(wd.segments)
    paces: dict[str, Pace] = voices.speaker_paces(wd, settings, segments) if voices.multi_speaker(settings, segments) else {}
    pace = voice_rate(wd, settings) if not paces else None
    caps = {}
    for i, s in enumerate(segments):
        own = paces.get(s.speaker) if paces else pace
        caps[s.id] = own.max_chars(translate._slot(segments, i))
    return segments, caps


def run(vid: str, translator: str) -> dict:
    root = BENCH / label(translator)
    wd = copy_of(vid, root)
    several = (WORK / vid / "diarization.json").exists() and any(
        s.get("speaker") for s in json.loads((WORK / vid / "segments.json").read_text()))
    settings = settings_for(translator, root, several)
    started = time.monotonic()
    try:
        result = translate.run(wd, settings, force=True)
    except SystemExit as e:
        return {"video": vid, "translator": translator, "failed": str(e), "seconds": round(time.monotonic() - started)}
    seconds = time.monotonic() - started
    segments, caps = budgets(wd, settings)
    shutil.copy(wd.translation, WORK / vid / f"translation.{label(translator)}.json")
    over = [s.id for s in result if len(s.text) > caps[s.id]]
    return {
        "video": vid, "translator": translator, "segments": len(result), "seconds": round(seconds),
        "ratio": round(sum(len(s.text) for s in result) / sum(len(s.text) for s in segments), 3),
        "over_budget": len(over), "over_budget_share": round(len(over) / len(result), 3),
        "over_1_25": sum(1 for s in result if len(s.text) > 1.25 * caps[s.id]),
        "several_voices": several,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--translator", action="append", required=True, metavar="BACKEND:MODEL")
    args = parser.parse_args()
    saved = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    for translator in args.translator:
        for vid in args.videos:
            row = run(vid, translator)
            saved.setdefault(translator, {})[vid] = row
            RESULTS.write_text(json.dumps(saved, ensure_ascii=False, indent=1))
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
