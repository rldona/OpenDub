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

### IndexTTS-2.5 (`--tts indextts`)
- Candidate added after Chatterbox: IndexTTS-2.5 (Bilibili IndexTeam, Spanish
  among its 5 languages) controls the length of what it says with
  `duration_factor` (0.5–2.0), so clips can be fitted to their slot natively
  instead of with atempo.
- Same benchmark as above (same 12 sentences and references): CER 1.5%,
  Spanish probability 0.97, ECAPA 0.58 (Chatterbox V3: 1.3%, 0.995, 0.54);
  real-time factor 0.39, 5.9 GB of VRAM, ~70 s to load the first time.
- New measure, on the 42 real segments of both videos with their slots: at
  its natural pace IndexTTS speaks slower than Chatterbox (11.8 vs 14.2
  chars/s) and only 11 clips fit. With `duration_factor` fitted to the slot,
  41/42 fit without atempo after up to two corrections (38 after one), versus
  30/42 for Chatterbox, which needed atempo on 11. The factor is accurate (the
  measured duration is 1.009× the target on average), so the pipeline predicts
  it from the calibrated speaking rate and corrects it once with the measured
  duration; atempo only covers what is left below the 0.5 floor. Fitting did
  not hurt intelligibility, accent or similarity (CER 0.2%, 0.99, ECAPA 0.54,
  the same as Chatterbox+atempo on those clips), and even fitted it speaks
  slower than Chatterbox after atempo (13.7 vs 14.8 chars/s).
- It runs in its own venv (Python 3.11, torch 2.8, transformers 4.52, pinned by
  its repo) as a separate process speaking JSON lines over stdin/stdout
  (`workers/indextts_worker.py`), installed with `opentranslator
  setup-indextts` from a pinned commit of its repo.
- **License: bilibili Model Use License Agreement** (not OSI-approved; governed
  by the laws of the People's Republic of China). It grants a worldwide,
  royalty-free, non-exclusive license, with these conditions relevant here:
  products above 100 million monthly active users or RMB 1 billion of annual
  revenue need a separate license; model outputs count as derivative works and
  may not be used to improve other AI models except IndexTTS itself or
  non-commercial ones; copies must keep the copyright notices and the license;
  some high-risk uses are excluded; the license can be revoked on breach.
  Fine for this personal tool, but more restrictive than Chatterbox's MIT.
- **Decision: Chatterbox stays the default engine of `--tts clone`; IndexTTS is
  chosen per video with `--engine indextts`.** IndexTTS won clearly on slot
  fitting, but not by ear across voices: watching both dubbed videos, it was
  preferred for the male voice and Chatterbox for the female one, where
  IndexTTS sometimes sounded as if trembling. The 3–9 Hz modulation agreed (see
  below). Two videos are too few to pick the engine from the voice's pitch, so
  the reference's mean F0 is logged and kept in `tts.json` next to the engine;
  after 8–10 dubbed videos that data will say whether a pitch rule makes sense
  as the default.
- IndexTTS fitting order: its speaking rate is calibrated at
  `duration_factor` 0.85 (its natural pace is slow, so calibrating at 1.0 made
  Claude cut translations more than needed: 9 sentences "probably too long" in
  one video, factors down to 0.5); clips are spoken at the slowest factor that
  fits between `--min-factor` (0.7 by default) and 1.0; whatever doesn't fit at
  the floor is shortened by Claude first, and only then compressed below it, down
  to 0.5, which is noted in `overflow.log`.
- Female-voice tremor: before blaming the model, IndexTTS was run on the same
  17 real segments (factor 1.0) with three other references of the same
  speaker (8–12 s, continuous speech, the least music under them). The 3–9 Hz
  loudness modulation dropped from 0.561 (current reference, the one with the
  most music under it: 14.9 dB of voice over the background vs 18–20 dB) to
  0.535–0.540 with two of them, Chatterbox's level, and rose to 0.591 with the
  third. Choosing references that way in the pipeline did not hold up in real
  dubs, though: with new translations and both engines the tremor went up for
  the female voice (IndexTTS 0.560 → 0.577, Chatterbox 0.530 → 0.589),
  similarity to the original voice fell in 3 of 4 dubs (by up to 0.027 ECAPA)
  and whisper heard less Spanish in the male one (p_es 0.993 → 0.95–0.97); by
  ear Chatterbox was still preferred for the female voice. The measure itself
  turned out to swing ±0.03–0.05 with the text alone, more than the effect, and
  on the 12 test sentences it even ranked IndexTTS below Chatterbox for the
  female voice. **Conclusion kept: the tremor comes from how IndexTTS clones
  that voice; the reference selection stays as it was (10–15 s, fewest
  pauses), and the 3–9 Hz measure is not reliable enough to judge it — the ear
  is.**
- The benchmark scripts (generators per model, CER, accent, similarity, F0,
  jitter and tremor) live in [bench/](bench/README.md); `uv run
  docs/bench/run.py <name>` scores a new model against the stored results.
