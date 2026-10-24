# OpenTranslator

Herramienta personal para doblar vídeos de YouTube al español con voz sintética,
sincronizada con el original.

```
URL → descarga (yt-dlp) → transcripción (subtítulos o faster-whisper)
    → traducción (Claude) → voz (edge-tts + atempo) → mezcla (numpy + ffmpeg) → MP4
```

## Instalación (macOS, Apple Silicon)

```bash
brew install ffmpeg uv
uv sync
```

Para traducir hay dos opciones:

- **Suscripción de Claude (por defecto, `--backend cli`)**: usa tu sesión de
  Claude Code. Instálalo y abre `claude` una vez para iniciar sesión:
  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```
- **API (`--backend api`)**: copia `.env.example` a `.env` y rellena
  `ANTHROPIC_API_KEY`.

## Uso

```bash
uv run opentranslator dub "https://www.youtube.com/watch?v=rwF-X5STYks" -o doblado.mp4
```

Opciones habituales de `dub`:

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--voice` | `es-ES-AlvaroNeural` | Voz de edge-tts (`es-ES-ElviraNeural`, `es-MX-JorgeNeural`…) |
| `--bg-volume` | `-15` | Volumen del audio original, en dB |
| `--mute-original` | no | Quita el audio original |
| `--subs` | `manual` | `manual`: subtítulos manuales o whisper · `auto`: también automáticos · `none`: siempre whisper |
| `--source-lang` | el de YouTube | Idioma original (si no se sabe, lo detecta whisper) |
| `--whisper-model` | `small` | Modelo de faster-whisper (`medium`, `large-v3`… más lentos) |
| `--backend` / `--model` | `cli` / `claude-sonnet-5-5` | Cómo y con qué modelo traducir |
| `--rate` | `-10%` | Velocidad nativa de la voz en edge-tts (más negativo = más despacio, sin estirar el audio) |
| `--chars-per-second` | calibrada | Velocidad de locución con la que se limita la longitud de cada traducción; por defecto se mide con la voz elegida |
| `--shorten` / `--no-shorten` | sí | Si una frase no cabe ni a `--max-tempo`, pedir a Claude una versión más corta y resintetizarla |
| `--max-tempo` / `--min-tempo` | `1.25` / `1.0` | Rango de atempo (`--min-tempo 0.9` permite ralentizar estirando el audio) |
| `--force` | no | Rehace todas las fases |

Cada fase también se puede lanzar sola, en orden: `download`, `transcribe`,
`translate`, `tts` y `mix` (todas aceptan la URL o el id del vídeo). Usa
`uv run opentranslator <fase> --help` para ver sus opciones.

## Caché y carpeta de trabajo

Todo se guarda en `work/<id del vídeo>/`. Cada fase se salta si ya se hizo con
los mismos parámetros, y al cambiar un parámetro solo se rehace esa fase y las
siguientes (por ejemplo, cambiar `--voice` repite TTS y mezcla, pero no la
traducción).

| Archivo | Contenido |
|---|---|
| `video.mp4`, `audio.wav`, `subs.*` | Descarga |
| `segments.json` | Frases originales con timestamps |
| `translation.json` | Traducción (puedes editarla a mano y relanzar `tts`) |
| `tts/`, `tts.json` | Un clip por frase, con su tempo, duración y el texto locutado (acortado si hizo falta) |
| `overflow.log` | Frases que no cupieron en su hueco, clips con duración anómala y clips retrasados |

La velocidad calibrada de cada voz se guarda en `work/voice_rates.json`; bórralo
para volver a medirla.
| `dub.wav`, `output.mp4` | Pista doblada y vídeo final |

## Limitaciones conocidas

- Si una frase no cabe ni a 1,25× tras dos rondas de acortado, el siguiente clip
  se retrasa en lugar de solaparse; el desfase se recupera en el siguiente silencio.
- faster-whisper corre en CPU (CTranslate2 no usa Metal): `small` transcribe unos
  2 minutos de audio en ~20 s.
- edge-tts usa un servicio no oficial de Microsoft y podría dejar de funcionar.
- Sin clonación de voz ni separación de voz y música (previsto para la v2).

## Tests

```bash
uv run pytest
```
