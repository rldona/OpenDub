"""Phase 5: compose the dubbed track and mux it with the original video.

The dubbed track is built in numpy (one clip per segment at its timestamp)
instead of with hundreds of `adelay` inputs in ffmpeg. If a clip does not fit
its slot, the next one is pushed forward instead of overlapping; the drift is
recovered at the next pause. Then a single ffmpeg call lowers the original
audio, mixes and copies the video without re-encoding.
"""

from __future__ import annotations

import json
import os
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .log import log
from .media import duration as media_duration
from .media import ffmpeg
from .tts import SAMPLE_RATE, Clip, load_clips
from .workdir import WorkDir

MIN_GAP = 0.08  # minimum silence between two pushed clips (s)


@dataclass
class Placement:
    id: int
    start: float  # actual position in the dubbed track
    delay: float  # delay relative to the original timestamp


def place(clips: list[Clip], min_gap: float = MIN_GAP) -> list[Placement]:
    """Place each clip at its timestamp or, if the previous one is still playing, right after it."""
    placements = []
    cursor = 0.0
    for c in sorted(clips, key=lambda c: c.start):
        start = c.start if c.start >= cursor else cursor + min_gap
        placements.append(Placement(c.id, round(start, 3), round(start - c.start, 3)))
        cursor = start + c.duration
    return placements


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
            raise ValueError(f"{path.name}: expected a mono wav at {SAMPLE_RATE} Hz")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def compose(clips: list[Clip], placements: list[Placement], base: Path, total: float) -> tuple[np.ndarray, int]:
    """Return the dubbed track and how many clips had to be cut at the end."""
    track = np.zeros(int(total * SAMPLE_RATE), dtype=np.float32)
    by_id = {c.id: c for c in clips}
    cut = 0
    for p in placements:
        audio = _read_wav(base / by_id[p.id].file)
        i = int(round(p.start * SAMPLE_RATE))
        if i >= len(track):
            cut += 1
            continue
        n = min(len(audio), len(track) - i)
        cut += n < len(audio)
        track[i : i + n] += audio[:n]
    return np.clip(track, -1.0, 1.0), cut


def _write_wav(path: Path, track: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((track * 32767).astype(np.int16).tobytes())


def filter_graph(settings: Settings, background: Path) -> tuple[list[str], str]:
    """Extra ffmpeg inputs and filter graph. Inputs 0 and 1 are the video and the dub.

    Priority: muted original (dub only) → separated background → original audio
    turned down.
    """
    dub = "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0"
    if settings.mute_original:
        log.info("Original audio muted")
        return [], f"{dub}[a]"
    if settings.separate:
        log.info(f"Separated background (music and effects) at {settings.music_volume_db:+.0f} dB")
        return ["-i", str(background)], (
            f"[2:a]aresample=48000,volume={settings.music_volume_db}dB[bg];"
            f"{dub}[dub];[bg][dub]amix=inputs=2:duration=first:normalize=0[a]"
        )
    log.info(f"Original audio at {settings.bg_volume_db:+.0f} dB")
    return [], (
        f"[0:a]volume={settings.bg_volume_db}dB[bg];"
        f"{dub}[dub];[bg][dub]amix=inputs=2:duration=first:normalize=0[a]"
    )


def archive(wd: WorkDir) -> Path | None:
    """Keep this dub as outputs/<engine>.mp4 (with its tts.json), next to the ones made with other engines.

    output.mp4 is always the latest dub; dubbing the video again with another
    engine no longer loses the previous one. A hard link: no extra disk space.
    """
    if not (wd.output.exists() and wd.tts_index.exists()):
        return None
    index = json.loads(wd.tts_index.read_text(encoding="utf-8"))
    engine = (index.get("engine") if isinstance(index, dict) else None) or "edge"
    wd.outputs_dir.mkdir(exist_ok=True)
    video = wd.outputs_dir / f"{engine}.mp4"
    if not (video.exists() and video.samefile(wd.output)):
        video.unlink(missing_ok=True)
        try:
            os.link(wd.output, video)
        except OSError:  # no hard links on this filesystem
            shutil.copyfile(wd.output, video)
    shutil.copyfile(wd.tts_index, wd.outputs_dir / f"{engine}.tts.json")
    if wd.overflow_log.exists():
        shutil.copyfile(wd.overflow_log, wd.outputs_dir / f"{engine}.overflow.log")
    return video


def run(wd: WorkDir, settings: Settings, force: bool = False, output: Path | None = None) -> Path:
    params = {
        "bg_volume_db": settings.bg_volume_db,
        "mute": settings.mute_original,
        "separate": settings.music_volume_db if settings.separate else None,
    }
    if settings.separate and not settings.mute_original and not wd.background.exists():
        raise SystemExit("--separate needs the separated background: run `separate` first (or use `dub --separate`)")
    if not force and wd.is_done("mix", params) and wd.output.exists():
        log.info("Mix cached, skipping")
    else:
        clips = load_clips(wd)
        total = media_duration(wd.video)
        placements = place(clips)
        delayed = [p for p in placements if p.delay > 0]
        if delayed:
            log.info(
                f"Clips delayed to avoid overlapping: {len(delayed)} "
                f"(max {max(p.delay for p in delayed):.2f}s)"
            )
            with wd.overflow_log.open("a", encoding="utf-8") as f:
                for p in delayed:
                    f.write(f"#{p.id} delayed {p.delay:.2f}s in the mix\n")

        track, cut = compose(clips, placements, wd.path, total)
        if cut:
            log.warning(f"{cut} clip(s) cut for running past the end of the video")
        _write_wav(wd.dub, track)

        inputs, graph = filter_graph(settings, wd.background)
        log.info("Mixing and muxing (video not re-encoded)…")
        ffmpeg(
            "-i", str(wd.video), "-i", str(wd.dub), *inputs,
            "-filter_complex", graph,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", "-movflags", "+faststart",
            str(tmp := wd.path / "output.part.mp4"),
        )
        # a new file, not output.mp4 rewritten in place: outputs/<engine>.mp4 is a hard link to it
        tmp.replace(wd.output)
        wd.mark_done("mix", params)
    archive(wd)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wd.output, output)
        log.info(f"Copied to {output}")
        return output
    log.info(f"Output: [bold]{wd.output}[/]")
    return wd.output
