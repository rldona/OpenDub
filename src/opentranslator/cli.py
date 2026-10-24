"""CLI: `dub` ejecuta el pipeline completo; el resto de comandos, una fase aislada."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import download as download_mod
from . import mix as mix_mod
from . import transcribe as transcribe_mod
from . import translate as translate_mod
from . import tts as tts_mod
from .config import Settings
from .log import log, phase
from .media import require_ffmpeg
from .workdir import WorkDir

app = typer.Typer(no_args_is_help=True, add_completion=False)

Url = Annotated[str, typer.Argument(help="URL de YouTube o id del vídeo")]
WorkRoot = Annotated[Path, typer.Option("--work", help="Carpeta raíz de trabajo")]
Force = Annotated[bool, typer.Option("--force", help="Regenerar aunque esté en caché")]
SourceLang = Annotated[
    str | None, typer.Option("--source-lang", help="Idioma original (por defecto, el de YouTube)")
]
MaxHeight = Annotated[int, typer.Option("--max-height", help="Altura máxima del vídeo")]
Subs = Annotated[
    str,
    typer.Option(
        "--subs",
        help="Subtítulos aceptados: manual (solo manuales), auto (manuales o automáticos), none (siempre whisper)",
    ),
]
WhisperModel = Annotated[str, typer.Option("--whisper-model", help="Modelo de faster-whisper")]
Backend = Annotated[
    str, typer.Option("--backend", help="cli (suscripción vía Claude Code) o api (ANTHROPIC_API_KEY)")
]
ClaudeModel = Annotated[str, typer.Option("--model", help="Modelo de Claude para traducir")]
Voice = Annotated[str, typer.Option("--voice", help="Voz de edge-tts (es-ES-…, es-MX-…)")]
BatchSize = Annotated[int, typer.Option("--batch-size", help="Segmentos por llamada de traducción")]
CharsPerSecond = Annotated[
    float | None,
    typer.Option(
        "--chars-per-second",
        help="Velocidad de locución para limitar la traducción (por defecto, se calibra con la voz)",
    ),
]
Rate = Annotated[
    str, typer.Option("--rate", help="Velocidad de la voz en edge-tts, p. ej. -10% (más lenta) o +5%")
]
Shorten = Annotated[
    bool,
    typer.Option("--shorten/--no-shorten", help="Retraducir más corto lo que no cabe ni a --max-tempo"),
]
MinTempo = Annotated[
    float, typer.Option("--min-tempo", help="Tempo mínimo (<1 ralentiza clips cortos; 1 = nunca)")
]
MaxTempo = Annotated[float, typer.Option("--max-tempo", help="Aceleración máxima con atempo")]
BgVolume = Annotated[
    float, typer.Option("--bg-volume", help="Volumen del audio original en dB (negativo = más bajo)")
]
MuteOriginal = Annotated[bool, typer.Option("--mute-original", help="Silenciar el audio original")]
Output = Annotated[
    Path | None, typer.Option("--output", "-o", help="Copiar el MP4 final a esta ruta")
]


def _setup(url: str, settings: Settings) -> WorkDir:
    require_ffmpeg()
    wd = WorkDir(settings.work_root, download_mod.video_id(url))
    log.info(f"Carpeta de trabajo: {wd.path}")
    return wd


def _require(wd: WorkDir, step: str) -> None:
    if not wd.has(step):
        raise typer.BadParameter(f"Falta la fase '{step}'. Ejecútala antes (o usa `dub`).")


@app.command()
def download(
    url: Url,
    work: WorkRoot = Path("work"),
    source_lang: SourceLang = None,
    max_height: MaxHeight = 1080,
    force: Force = False,
) -> None:
    """Descarga vídeo, audio y subtítulos."""
    settings = Settings(work_root=work, source_lang=source_lang, max_height=max_height)
    wd = _setup(url, settings)
    with phase("Descarga"):
        download_mod.run(url, wd, settings, force=force)


@app.command()
def transcribe(
    url: Url,
    work: WorkRoot = Path("work"),
    subs: Subs = "manual",
    whisper_model: WhisperModel = "small",
    force: Force = False,
) -> None:
    """Obtiene los segmentos con timestamps (subtítulos o whisper). Requiere `download`."""
    settings = Settings(work_root=work, subs=subs, whisper_model=whisper_model)
    wd = _setup(url, settings)
    _require(wd, "download")
    with phase("Transcripción"):
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
    """Traduce los segmentos al español con Claude. Requiere `transcribe`."""
    settings = Settings(
        work_root=work, backend=backend, claude_model=model, voice=voice, batch_size=batch_size,
        chars_per_second=chars_per_second, rate=rate,
    )
    wd = _setup(url, settings)
    _require(wd, "transcribe")
    with phase("Traducción"):
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
    """Genera un clip de voz por segmento y lo ajusta a su hueco. Requiere `translate`."""
    settings = Settings(
        work_root=work, voice=voice, rate=rate, min_tempo=min_tempo, max_tempo=max_tempo,
        shorten=shorten, backend=backend, claude_model=model,
    )
    wd = _setup(url, settings)
    _require(wd, "translate")
    with phase("TTS"):
        tts_mod.run(wd, settings, force=force)


@app.command()
def mix(
    url: Url,
    work: WorkRoot = Path("work"),
    bg_volume: BgVolume = -15.0,
    mute_original: MuteOriginal = False,
    output: Output = None,
    force: Force = False,
) -> None:
    """Compone la pista doblada y genera el MP4. Requiere `tts`."""
    settings = Settings(work_root=work, bg_volume_db=bg_volume, mute_original=mute_original)
    wd = _setup(url, settings)
    _require(wd, "tts")
    with phase("Mezcla"):
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
    output: Output = None,
    force: Force = False,
) -> None:
    """Pipeline completo: descarga → transcripción → traducción → TTS → mezcla."""
    settings = Settings(
        work_root=work, source_lang=source_lang, max_height=max_height,
        subs=subs, whisper_model=whisper_model, backend=backend, claude_model=model,
        voice=voice, batch_size=batch_size, chars_per_second=chars_per_second, rate=rate,
        min_tempo=min_tempo, shorten=shorten, max_tempo=max_tempo,
        bg_volume_db=bg_volume, mute_original=mute_original,
    )
    wd = _setup(url, settings)
    if force:
        wd.invalidate_from("download")
    with phase("Descarga"):
        download_mod.run(url, wd, settings)
    with phase("Transcripción"):
        transcribe_mod.run(wd, settings)
    with phase("Traducción"):
        translate_mod.run(wd, settings)
    with phase("TTS"):
        tts_mod.run(wd, settings)
    with phase("Mezcla"):
        mix_mod.run(wd, settings, output=output)


if __name__ == "__main__":
    app()
