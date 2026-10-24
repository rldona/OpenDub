"""CLI: `dub` runs the whole pipeline; every other command runs a single phase."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import download as download_mod
from . import mix as mix_mod
from . import separate as separate_mod
from . import transcribe as transcribe_mod
from . import translate as translate_mod
from . import tts as tts_mod
from .config import Settings
from .log import log, phase
from .media import require_ffmpeg
from .workdir import WorkDir

app = typer.Typer(no_args_is_help=True, add_completion=False)

Url = Annotated[str, typer.Argument(help="YouTube URL or video id")]
WorkRoot = Annotated[Path, typer.Option("--work", help="Root working folder")]
Force = Annotated[bool, typer.Option("--force", help="Regenerate even if cached")]
SourceLang = Annotated[
    str | None, typer.Option("--source-lang", help="Original language (defaults to YouTube's)")
]
MaxHeight = Annotated[int, typer.Option("--max-height", help="Maximum video height")]
Subs = Annotated[
    str,
    typer.Option(
        "--subs",
        help="Accepted subtitles: manual (manual only), auto (manual or auto-generated), none (always whisper)",
    ),
]
WhisperModel = Annotated[str, typer.Option("--whisper-model", help="faster-whisper model")]
Backend = Annotated[
    str, typer.Option("--backend", help="cli (subscription via Claude Code) or api (ANTHROPIC_API_KEY)")
]
ClaudeModel = Annotated[str, typer.Option("--model", help="Claude model used to translate")]
Voice = Annotated[str, typer.Option("--voice", help="edge-tts voice (es-ES-…, es-MX-…)")]
BatchSize = Annotated[int, typer.Option("--batch-size", help="Segments per translation call")]
CharsPerSecond = Annotated[
    float | None,
    typer.Option(
        "--chars-per-second",
        help="Speaking rate used to cap the translation (calibrated with the voice by default)",
    ),
]
Rate = Annotated[
    str, typer.Option("--rate", help="edge-tts speaking rate, e.g. -10% (slower) or +5%")
]
Shorten = Annotated[
    bool,
    typer.Option("--shorten/--no-shorten", help="Re-translate shorter whatever does not fit even at --max-tempo"),
]
MinTempo = Annotated[
    float, typer.Option("--min-tempo", help="Minimum tempo (<1 slows down short clips; 1 = never)")
]
MaxTempo = Annotated[float, typer.Option("--max-tempo", help="Maximum atempo speed-up")]
BgVolume = Annotated[
    float, typer.Option("--bg-volume", help="Original audio volume in dB (negative = quieter)")
]
MuteOriginal = Annotated[bool, typer.Option("--mute-original", help="Mute the original audio")]
Separate = Annotated[
    bool,
    typer.Option(
        "--separate/--no-separate",
        help="Mix over the separated background (music and effects, no original voice)",
    ),
]
Separator = Annotated[
    str, typer.Option("--separator", help="auto, mlx (Apple Silicon) or torch (CUDA or CPU)")
]
MusicVolume = Annotated[
    float, typer.Option("--music-volume", help="Separated background volume in dB")
]
Output = Annotated[
    Path | None, typer.Option("--output", "-o", help="Copy the final MP4 to this path")
]


def _setup(url: str, settings: Settings) -> WorkDir:
    require_ffmpeg()
    wd = WorkDir(settings.work_root, download_mod.video_id(url))
    log.info(f"Working folder: {wd.path}")
    return wd


def _require(wd: WorkDir, step: str) -> None:
    if not wd.has(step):
        raise typer.BadParameter(f"Phase '{step}' is missing. Run it first (or use `dub`).")


@app.command()
def download(
    url: Url,
    work: WorkRoot = Path("work"),
    source_lang: SourceLang = None,
    max_height: MaxHeight = 1080,
    force: Force = False,
) -> None:
    """Download the video, audio and subtitles."""
    settings = Settings(work_root=work, source_lang=source_lang, max_height=max_height)
    wd = _setup(url, settings)
    with phase("Download"):
        download_mod.run(url, wd, settings, force=force)


@app.command()
def transcribe(
    url: Url,
    work: WorkRoot = Path("work"),
    subs: Subs = "manual",
    whisper_model: WhisperModel = "small",
    force: Force = False,
) -> None:
    """Get timestamped segments (subtitles or whisper). Requires `download`."""
    settings = Settings(work_root=work, subs=subs, whisper_model=whisper_model)
    wd = _setup(url, settings)
    _require(wd, "download")
    with phase("Transcription"):
        transcribe_mod.run(wd, settings, force=force)


@app.command()
def translate(
    url: Url,
    work: WorkRoot = Path("work"),
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    voice: Voice = "es-ES-AlvaroNeural",
    batch_size: BatchSize = 30,
    chars_per_second: CharsPerSecond = None,
    rate: Rate = "-10%",
    force: Force = False,
) -> None:
    """Translate the segments into Spanish with Claude. Requires `transcribe`."""
    settings = Settings(
        work_root=work, backend=backend, claude_model=model, voice=voice, batch_size=batch_size,
        chars_per_second=chars_per_second, rate=rate,
    )
    wd = _setup(url, settings)
    _require(wd, "transcribe")
    with phase("Translation"):
        translate_mod.run(wd, settings, force=force)


@app.command()
def tts(
    url: Url,
    work: WorkRoot = Path("work"),
    voice: Voice = "es-ES-AlvaroNeural",
    rate: Rate = "-10%",
    min_tempo: MinTempo = 1.0,
    max_tempo: MaxTempo = 1.25,
    shorten: Shorten = True,
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    force: Force = False,
) -> None:
    """Generate one voice clip per segment and fit it to its slot. Requires `translate`."""
    settings = Settings(
        work_root=work, voice=voice, rate=rate, min_tempo=min_tempo, max_tempo=max_tempo,
        shorten=shorten, backend=backend, claude_model=model,
    )
    wd = _setup(url, settings)
    _require(wd, "translate")
    with phase("TTS"):
        tts_mod.run(wd, settings, force=force)


@app.command()
def separate(
    url: Url,
    work: WorkRoot = Path("work"),
    separator: Separator = "auto",
    force: Force = False,
) -> None:
    """Split the original audio into vocals and background. Requires `download`."""
    settings = Settings(work_root=work, separator=separator)
    wd = _setup(url, settings)
    _require(wd, "download")
    with phase("Separation"):
        separate_mod.run(wd, settings, force=force)


@app.command()
def mix(
    url: Url,
    work: WorkRoot = Path("work"),
    bg_volume: BgVolume = -15.0,
    mute_original: MuteOriginal = False,
    separate: Separate = False,
    music_volume: MusicVolume = 0.0,
    output: Output = None,
    force: Force = False,
) -> None:
    """Compose the dubbed track and produce the MP4. Requires `tts` (and `separate` with --separate)."""
    settings = Settings(
        work_root=work, bg_volume_db=bg_volume, mute_original=mute_original,
        separate=separate, music_volume_db=music_volume,
    )
    wd = _setup(url, settings)
    _require(wd, "tts")
    if separate:
        _require(wd, "separate")
    with phase("Mix"):
        mix_mod.run(wd, settings, force=force, output=output)


@app.command()
def dub(
    url: Url,
    work: WorkRoot = Path("work"),
    source_lang: SourceLang = None,
    max_height: MaxHeight = 1080,
    subs: Subs = "manual",
    whisper_model: WhisperModel = "small",
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    voice: Voice = "es-ES-AlvaroNeural",
    batch_size: BatchSize = 30,
    chars_per_second: CharsPerSecond = None,
    rate: Rate = "-10%",
    min_tempo: MinTempo = 1.0,
    max_tempo: MaxTempo = 1.25,
    shorten: Shorten = True,
    bg_volume: BgVolume = -15.0,
    mute_original: MuteOriginal = False,
    separate: Separate = False,
    separator: Separator = "auto",
    music_volume: MusicVolume = 0.0,
    output: Output = None,
    force: Force = False,
) -> None:
    """Full pipeline: download → transcription → translation → TTS → (separation) → mix."""
    settings = Settings(
        work_root=work, source_lang=source_lang, max_height=max_height,
        subs=subs, whisper_model=whisper_model, backend=backend, claude_model=model,
        voice=voice, batch_size=batch_size, chars_per_second=chars_per_second, rate=rate,
        min_tempo=min_tempo, shorten=shorten, max_tempo=max_tempo,
        bg_volume_db=bg_volume, mute_original=mute_original,
        separate=separate, separator=separator, music_volume_db=music_volume,
    )
    wd = _setup(url, settings)
    if force:
        wd.invalidate_from("download")
    with phase("Download"):
        download_mod.run(url, wd, settings)
    with phase("Transcription"):
        transcribe_mod.run(wd, settings)
    with phase("Translation"):
        translate_mod.run(wd, settings)
    with phase("TTS"):
        tts_mod.run(wd, settings)
    if separate:
        with phase("Separation"):
            separate_mod.run(wd, settings)
    with phase("Mix"):
        mix_mod.run(wd, settings, output=output)


if __name__ == "__main__":
    app()
