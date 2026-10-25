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
  (`workers/indextts_worker.py`), installed with `opendub
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
  as the default. Meanwhile the rule is available as opt-in `--engine auto`
  (IndexTTS below a 165 Hz reference F0, Chatterbox above), recorded in
  `tts.json` as `engine_choice`.
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

### More engines: CosyVoice 3, Fish S2 Pro, VoxCPM2 (evaluation)
- Three more candidates, benchmarked under the same conditions as Chatterbox and
  IndexTTS (same references, the same 12 sentences, the 42 dub segments of both
  short videos, seed 1234), each in its own venv under `work/_bench/<engine>/`
  with PyTorch 2.8 + CUDA 12.8 (RTX 5080, sm_120). The generators share one loop
  (`bench/generators/common.py`).
- **Licenses**:
  - **Fun-CosyVoice 3 0.5B** (Alibaba FunAudioLLM): **Apache 2.0**, code and
    weights.
  - **Fish Audio S2 Pro**: **Fish Audio Research License** (weights). Free for
    research and non-commercial use, personal use included; any commercial use
    needs a separate written license from Fish Audio; revocable; redistribution
    must carry the license and an attribution notice. The code is under the
    Fish Audio Community License.
  - **VoxCPM2** (OpenBMB): **Apache 2.0**, code and weights; 48 kHz output.
- **Fish S2 Pro discarded: it does not fit in 16 GB.** Its own requirement is at
  least 24 GB. It installs and runs on the RTX 5080 (from its uv.lock, without
  pyaudio, which only plays audio live), but the language model alone takes 14 GB
  once loaded — even with its KV cache cut from the model's 32k-token context
  (4.8 GB) to 4,096 tokens — and the 1.9 GB audio codec then fails to load. Making
  it fit would mean community 4-bit quantizations, which are no longer the model
  being evaluated.
- Results (A: the test sentences cloned from each video's own speaker; B: the
  dub segments with their slots). ECAPA is similarity to the original voice
  (same-speaker ceiling 0.89 male, 0.86 female); tremor is the 3–9 Hz pitch and
  loudness modulation; RTF and VRAM are over both videos; "factor ≥ 0.7" counts
  clips that fit using the native speed control no lower than the pipeline's
  default floor.

  | voice | engine | CER | p_es | ECAPA | tremor pitch/loud | chars/s | RTF | VRAM GB | fit without atempo | factor ≥ 0.7 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | male | Chatterbox V3 | 2.1% | 0.992 | 0.539 | 0.384/0.550 | 14.8 | 0.33 | 3.6 | 21/25 | — |
  | male | IndexTTS-2.5 | 1.6% | 0.955 | **0.568** | 0.416/0.556 | 11.3 | 0.39 | 5.9 | 24/25 | 20/25 |
  | male | CosyVoice 3 | 1.6% | **0.996** | 0.529 | **0.296/0.510** | 16.7 | 0.34 | 3.6 | **25/25** | **25/25** |
  | male | VoxCPM2 | 1.6% | 0.976 | 0.525 | 0.484/0.622 | 15.1 | 0.41 | 5.9 | 23/25 | — |
  | female | Chatterbox V3 | 0.5% | **0.997** | 0.533 | 0.505/0.647 | 13.4 | 0.33 | 3.6 | 9/17 | — |
  | female | IndexTTS-2.5 | 1.3% | 0.993 | 0.598 | **0.289/0.524** | 11.2 | 0.39 | 5.9 | **17/17** | 16/17 |
  | female | CosyVoice 3 | **0.0%** | 0.995 | 0.588 | 0.404/0.634 | 15.9 | 0.34 | 3.6 | **17/17** | 16/17 |
  | female | VoxCPM2 | 0.2% | 0.870 | **0.628** | 0.461/0.557 | 15.8 | 0.41 | 5.9 | 8/17 | — |

  The IndexTTS row is its plain configuration at the same seed (its `accel` mode
  is RTF 0.28 at 7.4 GB). On the fitted dub segments (B), CER stays at 0–0.4% for
  every engine except CosyVoice on the female voice (4.2%, from one clip) and
  VoxCPM2 on it (1.1%); Spanish probability 0.97–0.997 except VoxCPM2 female
  (0.894).
- What stands out:
  - **CosyVoice 3**: the fastest speaker (16–17 chars/s at its natural pace,
    against Chatterbox's 13–15 and IndexTTS's 11), so almost every segment fits
    as is: only 2 of 42 needed its `speed` control. That control stretches the
    mel spectrogram before the vocoder (a resampling of the voice, closer to
    atempo than to IndexTTS's `duration_factor`, which changes how the model
    paces itself). Least tremor on the male voice, native accent on both, light
    on VRAM (3.6 GB) and quick to load (9 s). Its weakness: one of the 42 segments
    came out garbled — "La IA generativa…" from the English female reference
    became 21.7 s of near-nonsense — which the pipeline's quality check would
    catch and regenerate. Cross-lingual mode (reference audio without its
    transcript) for the English speakers, zero-shot with the transcript for the
    Spanish reference, as its docs advise. The RL checkpoint (`llm.rl.pt`, lower
    CER in its paper) was not tried.
  - **VoxCPM2**: the closest to the original female voice (ECAPA 0.63, the best
    of all), but it carries her English over: whisper's Spanish probability
    0.87, against 0.99 for the others. The male voice sounds native (0.976).
    No numeric speed control (only a text instruction), and it speaks fast, but
    the female dub still fits only 8/17 without atempo. The most tremor on the
    male voice, the slowest (RTF 0.41), 5.9 GB, 21 s to load (70 s the first time, while it optimises itself).
- Listening folder in `bench/audio/listen/engines/<video>_<voice>/`
  (`<n>_<engine>.wav` per sentence, `all_<engine>.wav` for the five in a row,
  loudness-matched; built by `bench/listen.py`).
- **Decision, after listening: CosyVoice 3 is integrated (`--engine
  cosyvoice`); VoxCPM2 is not.** Integration:
  - `engines.py` is now the shared client of every engine that runs in its own
    venv (process start through `media.popen`, handshake, JSON-lines requests,
    shutdown); IndexTTS moved onto it. CosyVoice's worker is
    `workers/cosyvoice_worker.py`; its venv comes from
    `engines/cosyvoice/pyproject.toml` (with its `uv.lock`), installed with
    `setup-engine cosyvoice` from the benchmarked commit of its repo.
  - The IndexTTS-only fitting became "native duration" fitting for both
    engines (prediction from the calibrated pace, one measured correction,
    `--min-factor` floor, shortening, below the floor down to 0.5, atempo).
    CosyVoice is calibrated at factor 1.0: its natural pace is already fast.
  - Cross-lingual mode always (reference audio, no transcript), also for the
    fixed reference; clips written as 16-bit PCM.
  - `--keep-translation` (the web's *Regenerate with another engine*) reuses
    the translation made for another engine, so switching engines does not
    re-translate; what no longer fits is fitted in TTS as usual.
  - *Automatic* is unchanged (Chatterbox/IndexTTS by pitch): CosyVoice is picked
    by hand until more dubs say where it belongs.
- Real dubs from the web, same translations as the earlier engines: male video,
  24 clips, none sped up or shortened, one fitted with the factor (0.93), none
  redone by the quality check, voice phase 63 s. Female video, 17 clips, none
  sped up or shortened, one fitted (0.96); one clip failed the quality check
  through every retry and ended on edge-tts, the same sentence that came out
  garbled in the benchmark ("La IA generativa… «deepfakes»…"). Trying variants
  with the real worker showed it is not the acronym alone: with that
  reference, cross-lingual CosyVoice sometimes runs away on that sentence
  (29–42 s of near-random syllables), depending on the seed, with "IA" or
  "ia". Left to the quality check.
- 28-minute video, both engines on the same translation (made for CosyVoice's
  pace, so longer sentences than IndexTTS's own would have been), every Phase D
  improvement on: voice phase 438.8 s with CosyVoice, 431.5 s with IndexTTS
  (accelerated). The same time: CosyVoice redoes far less (4 sentences
  shortened, 4 below the floor, 3 clips redone and 1 on edge-tts, against 36,
  13 and 18 with 3 sped up), but IndexTTS generates faster per clip (RTF 0.28 vs
  0.34). The drop from the earlier 17.2 minutes with IndexTTS is Phase D's
  acceleration and quality-check speed-up, not the engine.

## Phase D — Speed
- Where the time goes, on a 28-minute video with IndexTTS: download 0.2 min,
  transcription 0.3, separation 0.4, translation 2.2, voice 21.7, mix 0.5. The
  voice phase is 86% of it, so that is where to work; overlapping translation
  with the voice would save at most 2 minutes.
- First, fewer clips to redo: figures written out in words, an overhead-plus-rate
  calibration (robust to a garbled calibration clip) and GPU memory released
  between jobs took the same video from 25.3 to 19.9 minutes (voice phase 21.7 →
  17.2), with 48 shortened sentences instead of 67 and 1 clip on edge-tts
  instead of 5.
- IndexTTS's own GPT2 acceleration engine (flash-attn, its `accel` extra): RTF
  0.367 → 0.280 (1.31×) over 3 seeds × 24 clips, with the same CER (0.009 vs
  0.010), Spanish probability (0.988 vs 0.983), similarity (ECAPA 0.577 vs 0.576)
  and no clip above 10% CER in either; +1.5 GB of VRAM (7.4 GB) and +7 s to
  load. A first single-seed run looked worse (CER 0.047), which more seeds showed
  to be sampling noise. torch.compile added only 4% and is left off; BigVGAN's
  fused CUDA kernel needs nvcc, not installed. flash-attn's prebuilt wheel runs on
  the RTX 5080 (sm_120) once its build script is told not to look for nvcc.
  Enabled by default when flash-attn is installed (`setup-indextts` does it).
- Quality-check whisper: loading the model once saves little (0.6 s per load from
  cache); greedy decoding halves the check (23.6 → 12.3 s on 353 clips) with the
  same verdict on 352 of them. Enabled.
- Chatterbox with two processes on the GPU: 3.64× → 5.00× real time (1.37×),
  3.6 GB each. Done later as a pool of two worker processes on the shared
  JSON-lines launcher (`workers/chatterbox_worker.py`, OpenDub's own venv), used
  when the GPU has 12 GB or more (`OPENDUB_CHATTERBOX_WORKERS` overrides it): on
  real dubs the voice phase went 320.9 → 254.2 s on the 19-minute video (1.26×)
  and 49.0 → 39.5 s and 62.9 → 56.9 s on the short ones (where the two processes'
  10 s start weighs more), with the same clips (same seeds: identical speed-ups,
  shortenings and quality-check redos).
