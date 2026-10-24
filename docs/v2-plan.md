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
- Benchmark on an M1 Pro (122 s and 155 s videos): HTDemucs on MLX took 8–10 s,
  Mel-Band RoFormer 73–85 s and BS-RoFormer 480–600 s. HTDemucs and Mel-Band
  left equally clean backgrounds (whisper found no speech in either), so HTDemucs
  was chosen: demucs-mlx on Apple Silicon, demucs on PyTorch/CUDA elsewhere.
- Repeated on an RTX 5080 (CUDA 12.8, same videos): HTDemucs 3.7–6.4 s including
  model load, Mel-Band RoFormer 4.5–5.9 s (+1.4 s load), BS-RoFormer 32–40 s
  (+7 s load). Whisper large-v3 found no speech in any of the backgrounds, and
  under speech HTDemucs left 0.6–1.5 dB less residue than both RoFormers. Mel-Band
  is now as fast, but with no measurable quality gain it doesn't justify a second
  backend: HTDemucs stays.
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
