"""Dub corpus videos with ElevenLabs (Dubbing API), to set them against OpenDub in a listening session.

    uv run python docs/bench/listening/elevenlabs_dub.py 17kBVfGjI8c rwF-X5STYks
    uv run python docs/bench/listening/elevenlabs_dub.py VD6xJq8NguY@263-413   # only that stretch (seconds)

Reads ELEVENLABS_API_KEY from the environment or .env (never printed). Sends each
work/<id>/video.mp4 from English to Spanish with the speakers detected automatically,
waits for it and saves the dub as work/_bench/external/elevenlabs/<id>.mp4 (not
committed: third-party video). With a stretch (<id>@start-end) only that part is dubbed
and billed, and it is saved as <id>.m4a on the video's own timeline (silence before
and after), so a session takes it like a whole dub. Then, for instance:

    uv run python docs/bench/listening/session.py make vs-others --videos 17kBVfGjI8c rwF-X5STYks \\
        --source opendub=chatterbox --source elevenlabs=file:work/_bench/external/elevenlabs/{video}.mp4 …

Dubbing is billed per minute of source. The free plan only dubs with a watermark on
the video (--watermark); its audio alone, with the original's picture, keeps a blind
session blind.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io/v1/dubbing"
WORK = Path("work")
OUT = WORK / "_bench" / "external" / "elevenlabs"
POLL_S = 10


def api_key() -> str:
    if key := os.environ.get("ELEVENLABS_API_KEY"):
        return key
    env = Path(".env")
    for line in env.read_text().splitlines() if env.exists() else []:
        name, _, value = line.partition("=")
        if name.strip() == "ELEVENLABS_API_KEY" and value.strip():
            return value.strip().strip('"').strip("'")
    sys.exit("ELEVENLABS_API_KEY is not set (environment or .env)")


def dub(client: httpx.Client, vid: str, source: str, target: str, watermark: bool,
        span: tuple[int, int] | None = None) -> Path:
    video = WORK / vid / "video.mp4"
    data = {"source_lang": source, "target_lang": target, "num_speakers": "0",
            "name": f"opendub-bench {vid}", "watermark": str(watermark).lower()}
    if span:
        data |= {"start_time": str(span[0]), "end_time": str(span[1])}
    with video.open("rb") as f:
        r = client.post(API, files={"file": (video.name, f, "video/mp4")}, data=data)
    if r.status_code >= 400:
        sys.exit(f"{vid}: the dub was refused ({r.status_code}): {r.text[:500]}")
    job = r.json()
    print(f"{vid}: dubbing {job['dubbing_id']} (expected ~{job.get('expected_duration_sec', '?')} s)", flush=True)
    while True:
        time.sleep(POLL_S)
        state = client.get(f"{API}/{job['dubbing_id']}").json()
        if state.get("status") == "dubbed":
            break
        if state.get("status") == "failed":
            sys.exit(f"{vid}: the dub failed: {state.get('error')}")
    r = client.get(f"{API}/{job['dubbing_id']}/audio/{target}")
    if r.status_code >= 400:
        sys.exit(f"{vid}: the download was refused ({r.status_code}): {r.text[:500]}")
    kind = r.headers.get("content-type", "")
    out = OUT / f"{vid}.{'mp4' if 'video' in kind else 'mp3' if 'mpeg' in kind else 'bin'}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"{vid}: saved {out} ({kind}, {len(r.content) / 1e6:.1f} MB)", flush=True)
    if span:
        out = on_timeline(out, video, span[0])
    return out


def on_timeline(stretch: Path, video: Path, start: float) -> Path:
    """The dub of a stretch as audio over the whole video's length: silence, the stretch at `start`, silence."""
    length = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                             str(video)], capture_output=True, text=True, check=True).stdout.strip()
    out = stretch.with_name(stretch.name.split(".")[0] + ".m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(stretch), "-vn",
                    "-af", f"adelay={int(start * 1000)}:all=1,apad", "-t", length, "-c:a", "aac", "-b:a", "192k",
                    str(out)], check=True)
    stretch.unlink()
    print(f"  placed at {start:.0f}s on the video's timeline: {out}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="es")
    parser.add_argument("--watermark", action="store_true",
                        help="the free plan only dubs with one (on the video: session.py can use the audio alone)")
    args = parser.parse_args()
    with httpx.Client(headers={"xi-api-key": api_key()}, timeout=httpx.Timeout(60.0, write=300.0)) as client:
        for arg in args.videos:
            vid, _, span = arg.partition("@")
            start, _, end = span.partition("-")
            dub(client, vid, args.source, args.target, args.watermark, (int(start), int(end)) if span else None)


if __name__ == "__main__":
    main()
