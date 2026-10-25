"""Cut the reference clips from vocals.wav and synthesize the fixed Spanish reference.

Run with OpenDub's env (edge-tts), after `dub` on both videos:
    uv run python docs/bench/generators/prep.py work
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).parent.parent / "audio"
WORK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("work")  # pipeline work folder (vocals.wav)
cfg = json.loads((HERE.parent / "sentences.json").read_text())
refs = HERE / "refs"
refs.mkdir(exist_ok=True)

for vid, r in cfg["refs"].items():
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(r["start"]), "-to", str(r["end"]),
                    "-i", str(WORK / vid / "stems" / "vocals.wav"), "-ac", "1", "-ar", "24000",
                    str(refs / f"{vid}.wav")], check=True)
    (refs / f"{vid}.txt").write_text(r["text"])


async def fixed():
    mp3 = refs / "fixed_es.mp3"
    await edge_tts.Communicate(cfg["fixed_es"], "es-ES-AlvaroNeural", rate="-10%").save(str(mp3))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ac", "1", "-ar", "24000",
                    str(refs / "fixed_es.wav")], check=True)
    (refs / "fixed_es.txt").write_text(cfg["fixed_es"])
    # baseline: the edge-tts voice itself saying the test sentences
    for vid, sents in cfg["sentences"].items():
        out = HERE / "out" / "edge" / f"{vid}__none"
        out.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(sents):
            await edge_tts.Communicate(s, "es-ES-AlvaroNeural", rate="-10%").save(str(out / f"{i}.mp3"))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / f"{i}.mp3"), "-ac", "1",
                            "-ar", "24000", str(out / f"{i}.wav")], check=True)
            (out / f"{i}.mp3").unlink()

asyncio.run(fixed())
for f in sorted(refs.glob("*.wav")):
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True).stdout.strip()
    print(f.name, d)
