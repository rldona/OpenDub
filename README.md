# OpenTranslator

A personal tool that dubs YouTube videos into Spanish with a synthetic voice,
kept in sync with the original.

```
URL → download (yt-dlp) → transcription (subtitles or faster-whisper)
    → translation (Claude) → voice (edge-tts + atempo) → mix (numpy + ffmpeg) → MP4
```

## Installation

macOS (Apple Silicon):

```bash
brew install ffmpeg uv
uv sync
```

Ubuntu (optionally with an NVIDIA GPU):

```bash
sudo apt install ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

Voice/music separation (`--separate`) needs an optional extra: it installs
demucs-mlx on Apple Silicon, and demucs with PyTorch (CUDA 12.8 wheels, which RTX
50-series GPUs require) on Linux:

```bash
uv sync --extra separate
```

On Linux, whisper and the separator use the NVIDIA GPU automatically when one is
available; on a Mac, whisper runs on the CPU and the separator on the Apple GPU.

Voice cloning (`--tts clone`) needs another extra, with Chatterbox Multilingual V3
(installed from a pinned GitHub commit, since it isn't on PyPI yet). It also needs
the separation, so install both:

```bash
uv sync --extra separate --extra clone
```

There are two ways to translate:

- **Claude subscription (default, `--backend cli`)**: uses your Claude Code
  session. Install it and run `claude` once to sign in:
  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```
- **API (`--backend api`)**: copy `.env.example` to `.env` and fill in
  `ANTHROPIC_API_KEY`.

## Usage

```bash
uv run opentranslator dub "https://www.youtube.com/watch?v=rwF-X5STYks" -o dubbed.mp4
```

Common `dub` options:

| Option | Default | What it does |
|---|---|---|
| `--voice` | `es-ES-AlvaroNeural` | edge-tts voice (`es-ES-ElviraNeural`, `es-MX-JorgeNeural`…) |
| `--tts` | `edge` | `edge`: the `--voice` voice · `clone`: the original speaker's voice, cloned from the separated vocals |
| `--clone-ref` | none | Fixed Spanish recording to clone from when a cloned clip fails the quality check |
| `--bg-volume` | `-15` | Volume of the original audio, in dB |
| `--mute-original` | off | Drops the original audio |
| `--separate` | off | Mixes over the separated background (music and effects, without the original voice) instead of the turned-down original |
| `--music-volume` | `0` | Volume of the separated background, in dB |
| `--separator` | `auto` | `mlx` (Apple Silicon) or `torch` (CUDA or CPU); `auto` picks by platform |
| `--subs` | `manual` | `manual`: manual subtitles or whisper · `auto`: auto-generated ones too · `none`: always whisper |
| `--source-lang` | YouTube's | Original language (whisper detects it when unknown) |
| `--whisper-model` | `small` | faster-whisper model (`medium`, `large-v3`… are slower) |
| `--backend` / `--model` | `cli` / `claude-sonnet-5-5` | How and with which model to translate |
| `--rate` | `-10%` | Native edge-tts speaking rate (more negative = slower, without stretching the audio) |
| `--chars-per-second` | calibrated | Speaking rate used to cap each translation's length; measured with the chosen voice by default |
| `--shorten` / `--no-shorten` | on | If a sentence doesn't fit even at `--max-tempo`, ask Claude for a shorter version and re-synthesize it |
| `--max-tempo` / `--min-tempo` | `1.25` / `1.0` | atempo range (`--min-tempo 0.9` allows slowing down by stretching the audio) |
| `--force` | off | Redoes every phase |

Each phase can also run on its own: `download`, `transcribe`, `translate`, `tts`,
`separate` and `mix` (all accept the URL or the video id). `separate` only needs
`download`, so it can run at any point before `mix --separate`. Run
`uv run opentranslator <phase> --help` to see its options.

## Cache and working folder

Everything is stored in `work/<video id>/`. A phase is skipped if it already ran
with the same parameters, and changing a parameter only redoes that phase and the
ones that depend on it (for example, changing `--voice` repeats TTS and mixing,
but neither the translation nor the separation).

| File | Contents |
|---|---|
| `video.mp4`, `audio.wav`, `subs.*` | Download |
| `segments.json` | Original sentences with timestamps |
| `translation.json` | Translation (you can edit it by hand and rerun `tts`) |
| `tts/`, `tts.json` | One clip per sentence, with its tempo, duration and spoken text (shortened if needed) |
| `overflow.log` | Sentences that didn't fit their slot, clips with abnormal duration and delayed clips |
| `stems/vocals.wav`, `stems/background.wav` | Separated original voice and background |
| `clone_ref.wav` | 10–15 s of the original speaker used as the cloning reference (`--tts clone`) |
| `dub.wav`, `output.mp4` | Dubbed track and final video |

Each voice's calibrated speaking rate is stored in `work/voice_rates.json`;
delete it to measure again.

## Voice cloning

With `--tts clone`, `dub` separates the audio right after transcribing it,
picks the 10–15 s stretch of the original speaker with the fewest pauses as the
reference and measures the cloned voice's speaking rate before translating.
Every cloned clip is transcribed back with whisper (`--whisper-model`); one
whose text doesn't match, or whose duration is abnormal, goes down a fallback
chain that keeps the same voice as long as possible:

1. Regenerate with another seed.
2. Regenerate with a shorter version of the sentence, written by Claude.
3. Clone from the fixed reference (`--clone-ref`), if one was given.
4. edge-tts (`--voice`) as a last resort, recorded in `overflow.log`.

`tts.json` records which of these produced each clip. Chatterbox adds Resemble
AI's inaudible Perth watermark to everything it generates.

## Known limitations

- If a sentence still doesn't fit at 1.25× after two shortening rounds, the next
  clip is delayed instead of overlapping; the drift is recovered at the next pause.
- On a Mac, faster-whisper runs on the CPU (CTranslate2 doesn't use Metal):
  `small` transcribes about 2 minutes of audio in ~20 s.
- edge-tts relies on an unofficial Microsoft service and could stop working.
- Voice cloning follows a single speaker (the one in the reference); videos
  with several voices are all dubbed with that one.
- On Linux, whisper uses the GPU only when cuBLAS and cuDNN can be loaded: they
  come with `uv sync --extra separate` (PyTorch's CUDA wheels) or a system CUDA
  install; otherwise it falls back to the CPU with a warning. Tested on an RTX
  5080: `large-v3` transcribes 2.5 minutes of audio in ~10 s.

## Tests

```bash
uv run pytest
```
