"""CLI: `dub` runs the whole pipeline; every other command runs a single phase."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import download as download_mod
from . import pipeline
from . import mix as mix_mod
from . import separate as separate_mod
from . import style as style_mod
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
Tts = Annotated[
    str,
    typer.Option("--tts", help="edge (edge-tts voice) or clone (the original speaker's voice; needs `separate`)"),
]
Engine = Annotated[
    str,
    typer.Option(
        "--engine",
        help="Cloning engine for --tts clone: chatterbox, indextts, cosyvoice, or auto (by the reference's pitch: "
        "IndexTTS below 165 Hz, Chatterbox above)",
    ),
]
MinFactor = Annotated[
    float,
    typer.Option(
        "--min-factor",
        help="indextts, cosyvoice: lowest duration factor before shortening the sentence "
        "(it goes down to 0.5 only after that)",
    ),
]
KeepTranslation = Annotated[
    bool,
    typer.Option(
        "--keep-translation",
        help="Reuse the existing translation even if it was made for another voice (e.g. another engine): "
        "only TTS and the mix are redone",
    ),
]
CloneRef = Annotated[
    Path | None,
    typer.Option("--clone-ref", help="Fixed Spanish reference recording for cloned clips that fail the quality check"),
]
MultiSpeaker = Annotated[
    bool,
    typer.Option(
        "--multi-speaker",
        help="Several voices: tell who speaks each sentence (NVIDIA Nemotron 3 Diarization, "
        "`setup-engine nemotron`) and give each speaker their own voice",
    ),
]
StyleFile = Annotated[
    Path | None,
    typer.Option(
        "--style",
        help="style.json with register (tu/usted), variant (es-ES/latam), glossary terms and notes; "
        "applied over work/style.json and the video's own work/<id>/style.json",
    ),
]
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
Loudness = Annotated[
    float,
    typer.Option("--loudness", help="Integrated loudness of the final track in LUFS (EBU R128), with a -1.5 dBTP "
                 "true-peak ceiling; 0 leaves it as mixed"),
]
Output = Annotated[
    Path | None, typer.Option("--output", "-o", help="Copy the final MP4 to this path")
]


_held = contextlib.ExitStack()  # a phase command holds its video until the process ends


def _setup(url: str, settings: Settings) -> WorkDir:
    require_ffmpeg()
    wd = WorkDir(settings.work_root, download_mod.video_id(url))
    log.info(f"Working folder: {wd.path}")
    _held.enter_context(wd.lock(f"opendub {sys.argv[1] if len(sys.argv) > 1 else 'cli'}"))
    return wd


def _with_style(settings: Settings, wd: WorkDir) -> Settings:
    """The edge-tts voice of the style's variant, if it asks for the other one."""
    return style_mod.with_variant_voice(settings, style_mod.load(settings.work_root, wd.path, settings.style_file))


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
    multi_speaker: MultiSpeaker = False,
    force: Force = False,
) -> None:
    """Get timestamped segments (subtitles or whisper). Requires `download` (and `diarize` with --multi-speaker)."""
    settings = Settings(work_root=work, subs=subs, whisper_model=whisper_model, multi_speaker=multi_speaker)
    wd = _setup(url, settings)
    _require(wd, "download")
    if multi_speaker:
        _require(wd, "diarize")
    with phase("Transcription"):
        transcribe_mod.run(wd, settings, force=force)


@app.command()
def translate(
    url: Url,
    work: WorkRoot = Path("work"),
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    voice: Voice = "es-ES-AlvaroNeural",
    tts: Tts = "edge",
    engine: Engine = "chatterbox",
    batch_size: BatchSize = 30,
    chars_per_second: CharsPerSecond = None,
    rate: Rate = "-10%",
    style: StyleFile = None,
    force: Force = False,
) -> None:
    """Translate the segments into Spanish with Claude. Requires `transcribe` (and `separate` with --tts clone)."""
    settings = Settings(
        work_root=work, backend=backend, claude_model=model, voice=voice, tts=tts, engine=engine, batch_size=batch_size,
        chars_per_second=chars_per_second, rate=rate, style_file=style,
    )
    wd = _setup(url, settings)
    settings = _with_style(settings, wd)
    _require(wd, "transcribe")
    if tts != "edge":
        _require(wd, "separate")
    with phase("Translation"):
        translate_mod.run(wd, settings, force=force)


@app.command()
def tts(
    url: Url,
    work: WorkRoot = Path("work"),
    voice: Voice = "es-ES-AlvaroNeural",
    tts: Tts = "edge",
    engine: Engine = "chatterbox",
    min_factor: MinFactor = 0.7,
    clone_ref: CloneRef = None,
    whisper_model: WhisperModel = "small",
    rate: Rate = "-10%",
    min_tempo: MinTempo = 1.0,
    max_tempo: MaxTempo = 1.25,
    shorten: Shorten = True,
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    style: StyleFile = None,
    force: Force = False,
) -> None:
    """Generate one voice clip per segment and fit it to its slot. Requires `translate` (and `separate` with --tts clone)."""
    settings = Settings(
        work_root=work, voice=voice, tts=tts, engine=engine, min_factor=min_factor, clone_ref=clone_ref,
        whisper_model=whisper_model, rate=rate,
        min_tempo=min_tempo, max_tempo=max_tempo, shorten=shorten, backend=backend, claude_model=model,
        style_file=style,
    )
    wd = _setup(url, settings)
    settings = _with_style(settings, wd)
    _require(wd, "translate")
    if tts != "edge":
        _require(wd, "separate")
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
def diarize(
    url: Url,
    work: WorkRoot = Path("work"),
    force: Force = False,
) -> None:
    """Tell who speaks when, for --multi-speaker (Nemotron 3 Diarization). Requires `separate`."""
    from . import diarize as diarize_mod

    settings = Settings(work_root=work)
    wd = _setup(url, settings)
    _require(wd, "separate")
    with phase("Separation"):
        diarize_mod.run(wd, settings, force=force)


@app.command()
def mix(
    url: Url,
    work: WorkRoot = Path("work"),
    bg_volume: BgVolume = -15.0,
    mute_original: MuteOriginal = False,
    separate: Separate = False,
    music_volume: MusicVolume = 0.0,
    loudness: Loudness = -16.0,
    output: Output = None,
    force: Force = False,
) -> None:
    """Compose the dubbed track and produce the MP4. Requires `tts` (and `separate` with --separate)."""
    settings = Settings(
        work_root=work, bg_volume_db=bg_volume, mute_original=mute_original,
        separate=separate, music_volume_db=music_volume, loudness_lufs=loudness or None,
    )
    wd = _setup(url, settings)
    _require(wd, "tts")
    if separate:
        _require(wd, "separate")
    with phase("Mix"):
        mix_mod.run(wd, settings, force=force, output=output)


@app.command()
def retouch(
    url: Url,
    work: WorkRoot = Path("work"),
    take: Annotated[
        list[int] | None,
        typer.Option("--take", help="Segment id to speak again with another take (repeat it for several)"),
    ] = None,
    clone_ref: CloneRef = None,
    min_factor: MinFactor = 0.7,
    whisper_model: WhisperModel = "small",
    voice: Voice = "es-ES-AlvaroNeural",
    rate: Rate = "-10%",
    max_tempo: MaxTempo = 1.25,
    shorten: Shorten = True,
    backend: Backend = "cli",
    model: ClaudeModel = "claude-sonnet-5-5",
    bg_volume: BgVolume = -15.0,
    mute_original: MuteOriginal = False,
    separate: Separate = False,
    music_volume: MusicVolume = 0.0,
    loudness: Loudness = -16.0,
    output: Output = None,
) -> None:
    """Speak again the sentences edited since the latest dub (and any --take), then mix a new version.

    With the dub's own engine. Hand-edited sentences are never shortened. Requires a dub.
    """
    settings = Settings(
        work_root=work, clone_ref=clone_ref, min_factor=min_factor, whisper_model=whisper_model, voice=voice,
        rate=rate, max_tempo=max_tempo, shorten=shorten, backend=backend, claude_model=model,
        bg_volume_db=bg_volume, mute_original=mute_original, separate=separate, music_volume_db=music_volume,
        loudness_lufs=loudness or None, retouch=tuple(take or ()),
    )
    pipeline.retouch(url, settings, output=output)


@app.command()
def export(
    url: Url,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="srt (the dubbed voice, timed as heard), srt-orig (the original), "
                     "mkv (video, dubbed and original audio, both subtitles) or m4a (the dubbed audio)"),
    ] = "mkv",
    version: Annotated[
        str | None, typer.Option("--version", help="A kept version (outputs/<version>.mp4); the latest by default"),
    ] = None,
    work: WorkRoot = Path("work"),
    output: Output = None,
) -> None:
    """Export a dub as subtitles, an MKV with both audio tracks or its audio, without re-encoding."""
    import shutil

    from . import export as export_mod

    require_ffmpeg()
    wd = WorkDir(work, download_mod.video_id(url), create=False)
    try:
        path = export_mod.export(wd, fmt, version)
    except LookupError as e:
        raise typer.BadParameter(f"No such dub: {e}") from e
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        path = output
    log.info(f"Exported: [bold]{path}[/]")


@app.command()
def web(
    work: WorkRoot = Path("work"),
    port: Annotated[int, typer.Option("--port", help="Port on 127.0.0.1")] = 8000,
    browser: Annotated[bool, typer.Option("--browser/--no-browser", help="Open the page in the browser")] = True,
) -> None:
    """Local web frontend: paste a URL, follow the progress, watch and fix the dubs."""
    try:
        from .web.app import create_app, serve
    except ImportError:
        raise SystemExit("The web frontend needs its optional dependencies: uv sync --extra web")
    require_ffmpeg()
    url = f"http://127.0.0.1:{port}/"
    if browser:
        import threading
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    log.info(f"OpenDub web on [bold]{url}[/] (Ctrl+C to stop)")
    serve(create_app(work), port)


@app.command("setup-indextts")
def setup_indextts(
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Install folder (default: $OPENDUB_INDEXTTS_DIR or ~/.local/share/opendub/indextts)"),
    ] = None,
) -> None:
    """Install IndexTTS-2.5 for --engine indextts (same as `setup-engine indextts`)."""
    from . import indextts

    indextts.setup(path or Settings().indextts_dir)


@app.command("setup-engine")
def setup_engine(
    name: Annotated[str, typer.Argument(help="indextts, cosyvoice or nemotron (diarization, for --multi-speaker)")],
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Install folder (default: $OPENDUB_<NAME>_DIR or "
                     "~/.local/share/opendub/<name>)"),
    ] = None,
) -> None:
    """Install an engine that runs in its own venv: its code, the venv and the weights."""
    from . import cosyvoice, diarize, indextts

    if name == "indextts":
        indextts.setup(path or Settings().indextts_dir)
    elif name == "cosyvoice":
        cosyvoice.setup(path or Settings().cosyvoice_dir)
    elif name == "nemotron":
        diarize.setup(path or Settings().nemotron_dir)
    else:
        raise typer.BadParameter("the engines with their own venv are indextts, cosyvoice and nemotron")


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
    tts: Tts = "edge",
    engine: Engine = "chatterbox",
    min_factor: MinFactor = 0.7,
    clone_ref: CloneRef = None,
    keep_translation: KeepTranslation = False,
    multi_speaker: MultiSpeaker = False,
    style: StyleFile = None,
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
    loudness: Loudness = -16.0,
    output: Output = None,
    force: Force = False,
) -> None:
    """Full pipeline: download → transcription → (separation) → translation → TTS → mix.

    Separation runs before translation with a cloned voice, since its
    speaking rate (measured from the separated vocals) caps the translation length.
    """
    settings = Settings(
        work_root=work, source_lang=source_lang, max_height=max_height,
        subs=subs, whisper_model=whisper_model, backend=backend, claude_model=model,
        voice=voice, tts=tts, engine=engine, min_factor=min_factor, clone_ref=clone_ref,
        keep_translation=keep_translation, multi_speaker=multi_speaker, style_file=style, batch_size=batch_size, chars_per_second=chars_per_second, rate=rate,
        min_tempo=min_tempo, shorten=shorten, max_tempo=max_tempo,
        bg_volume_db=bg_volume, mute_original=mute_original,
        separate=separate, separator=separator, music_volume_db=music_volume, loudness_lufs=loudness or None,
    )
    pipeline.dub(url, settings, output=output, force=force)


if __name__ == "__main__":
    app()
