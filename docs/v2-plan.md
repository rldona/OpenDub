# v2 plan

Phases ordered by risk and value: first the safe work that improves results
today, voice cloning (the most uncertain part) last.

## Phase A — Slot fitting and quality (no new dependencies)
- Calibrate each voice's real speaking rate (voice + `--rate`) by synthesizing
  reference sentences before translating, and use it for `max_chars`. Cached
  per voice.
- Re-translate what doesn't fit: if a clip doesn't fit even at `--max-tempo`,
  ask Claude for a shorter version of that sentence and re-synthesize it (up to
  2 rounds).
- Cheap quality check: detect clips whose duration is abnormal for their text
  length (empty, cut off, repetitions) and regenerate them once.
- `--rate=-10%` by default.

## Phase B — Voice and music separation
- New `separate` phase (cached and runnable on its own, like the others) that
  produces `stems/vocals.wav` and `stems/background.wav`.
- Benchmark first: Mel-Band RoFormer (`audio-separator`) vs HTDemucs on MLX;
  pick by quality and speed on Apple Silicon.
- `mix` uses `background.wav` at 0 dB when it exists (`--separate`).
- Heavy dependencies in an optional extra.

## Phase C — Voice cloning
- Benchmark: Qwen3-TTS (MLX; confirm the Apache 2.0 license on the model card)
  vs Chatterbox Multilingual (MIT, with Perth audio watermarking).
- `--tts edge|clone` engine; edge-tts stays the default and the fallback.
- Reference: a 10–15 s sample extracted from `vocals.wav` with its transcript,
  **or a fixed Spanish reference** (your own file or a stock voice) as plan B if
  the English accent isn't convincing.
- A single speaker (the main one); diarization left for v3.
- Optional whisper-based quality check; recalibrate the speaking rate per engine.
