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
- Benchmark on an M1 Pro (122 s and 155 s videos): HTDemucs took 8–10 s,
  Mel-Band RoFormer 73–85 s and BS-RoFormer 480–600 s. HTDemucs and Mel-Band
  left equally clean backgrounds (whisper found no speech in either), so HTDemucs
  was chosen.
- Repeated on an RTX 5080 (CUDA 12.8, same videos): HTDemucs 3.7–6.4 s including
  model load, Mel-Band RoFormer 4.5–5.9 s (+1.4 s load), BS-RoFormer 32–40 s
  (+7 s load). Whisper large-v3 found no speech in any of the backgrounds, and
  under speech HTDemucs left 0.6–1.5 dB less residue than both RoFormers. Mel-Band
  is now as fast, but with no measurable quality gain it doesn't justify a second
  backend: HTDemucs stays.
- `mix` uses `background.wav` at 0 dB when it exists (`--separate`).
- Heavy dependencies in an optional extra.

## Phase C — Voice cloning
- Benchmark three candidates on CUDA: Qwen3-TTS 1.7B Base (Apache 2.0),
  Chatterbox Multilingual V3 (MIT, with Perth audio watermarking) and its Spain
  Spanish finetune (`ResembleAI/Chatterbox-Multilingual-es-es`, MIT), which is
  the most likely to fix the main risk: an English accent carried over from the
  reference.
- Measure speed, VRAM, intelligibility (whisper transcribes the Spanish output
  back and it's compared with the text), speaking rate and voice similarity to
  the reference with speaker embeddings (resemblyzer or SpeechBrain ECAPA). The
  embedding score gives a comparable number across candidates and references,
  but doesn't replace listening.
- Results on the RTX 5080 (12 Spanish sentences per candidate, references from
  both videos): Qwen3-TTS was the closest to the original voice (ECAPA 0.77
  against a 0.88 same-speaker ceiling) but carried the English accent over:
  whisper took several sentences for English (Spanish probability 0.55 on
  average, down to 0.08). Both Chatterbox models sounded native (0.99) with
  ECAPA 0.54–0.57, a third of the time on the GPU (real-time factor ~0.3 vs
  0.69) and less VRAM (3.6 vs 4.6 GB). With the fixed Spanish reference all
  three just sounded like that reference. **Chatterbox Multilingual V3 was
  chosen after listening.** Its pins (torch 2.6, numpy 1.x, gradio) are lifted
  with uv overrides in the `clone` extra.
- `--tts edge|clone` engine; edge-tts stays the default.
- Reference: a 10–15 s sample extracted from `vocals.wav` with its transcript,
  **or a fixed Spanish reference** (your own file or a stock voice) as plan B if
  the English accent isn't convincing.
- A single speaker (the main one); diarization left for v3.
- Whisper-based quality check; recalibrate the speaking rate per engine and
  reference.
- A clip that fails the check must not switch voices mid-video, so the fallback
  order is: regenerate with another seed → regenerate with a sentence shortened
  by Claude → clone with the fixed Spanish reference → edge-tts only as a last
  resort, logged in `overflow.log`.
