"""Listening folder: the same test sentences from each engine, side by side, per voice.

    python docs/bench/listen.py <name>… [--sentences 5]

Writes audio/listen/engines/<video>_<voice>/ with, for each sentence n,
<n>_<engine>.wav (cloned from that video's speaker), so a file manager lists the
engines of one sentence next to each other; all_<engine>.wav, the same sentences
one after another; and 0_reference_english.wav, the voice being cloned. Every
file is loudness-normalised (EBU R128, -20 LUFS) to 48 kHz mono, so neither level
nor sample rate tips the comparison. Needs only ffmpeg.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
CFG = json.loads((HERE / "sentences.json").read_text())
VOICE = {"17kBVfGjI8c": "male", "rwF-X5STYks": "female"}
NORM = "loudnorm=I=-20:TP=-1.5:LRA=11"


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def normalised(src: Path, dst: Path) -> None:
    ffmpeg("-i", str(src), "-af", NORM, "-ac", "1", "-ar", "48000", str(dst))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="+", help="model folders under audio/out")
    ap.add_argument("--sentences", type=int, default=5)
    args = ap.parse_args()
    root = AUDIO / "listen" / "engines"
    shutil.rmtree(root, ignore_errors=True)
    for vid in CFG["sentences"]:
        d = root / f"{vid}_{VOICE[vid]}"
        d.mkdir(parents=True)
        normalised(AUDIO / "refs" / f"{vid}.wav", d / "0_reference_english.wav")
        for name in args.names:
            parts = []
            for i in range(args.sentences):
                out = d / f"{i + 1}_{name}.wav"
                normalised(AUDIO / "out" / name / f"{vid}__{vid}" / f"{i}.wav", out)
                parts.append(out)
            # the sentences with 0.7 s of silence between them
            inputs = [x for p in parts for x in ("-i", str(p))]
            chain = "".join(f"[{k}]apad=pad_dur=0.7[a{k}];" for k in range(len(parts)))
            chain += "".join(f"[a{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1"
            ffmpeg(*inputs, "-filter_complex", chain, "-ar", "48000", str(d / f"all_{name}.wav"))
        print(f"{d.relative_to(HERE)}: {len(list(d.iterdir()))} files")


if __name__ == "__main__":
    main()
