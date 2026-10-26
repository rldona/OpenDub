# Voice benchmarks

The scripts behind the engine choices in [../v2-plan.md](../v2-plan.md): they
generate the same test material with each voice model and score it the same way,
so a new model can be compared with one command.

```bash
uv run docs/bench/run.py <name>        # score a new model's clips against all the others
uv run docs/bench/run.py --all         # rescore every model with clips on disk
uv run docs/bench/run.py --refs docs/bench/audio/fit/indextts_alt   # alternative references
uv run docs/bench/run.py --compare chatterbox_v3 indextts cosyvoice3 voxcpm2   # one table per video
python docs/bench/listen.py chatterbox_v3 indextts cosyvoice3 voxcpm2   # listening folder
```

`run.py` declares its own dependencies (faster-whisper, resemblyzer, SpeechBrain,
librosa, PyTorch with CUDA), so uv installs them on the first run; it needs an
NVIDIA GPU. Scores are written to `results/<name>.json` and committed, so the
comparison table still includes models whose clips are gone.

## What is measured

On **(A) 12 Spanish test sentences** (`sentences.json`, six per video), cloned
from each video's speaker and from a fixed Spanish reference:

- **CER**: whisper large-v3 transcribes the clip back in Spanish; character error
  rate against the text (ignoring case and punctuation).
- **p_es**: whisper's probability that the clip is Spanish when the language is
  not forced, a proxy for an accent carried over from the reference.
- **Similarity**: cosine of speaker embeddings (SpeechBrain ECAPA and
  resemblyzer) against the original speaker and against the fixed reference.
- **Speed**: real-time factor, VRAM, load time and speaking rate (chars/s).
- **Stability**: median F0, jitter (pitch change between 10 ms frames) and
  tremor, the share of pitch and loudness modulation in 3–9 Hz, where audible
  trembling lives.

On **(B) the real dub segments** of both videos with their slots (`audio/fit/`):
how many clips fit without atempo, and the same CER, p_es, ECAPA and stability.

## Adding a model

1. Run `generators/prep.py` once (after `dub` on both videos) to cut the
   references into `audio/refs/`.
2. Write a generator like the ones in `generators/`, in the model's own venv:
   one wav per sentence in `audio/out/<name>/<video>__<reference>/<i>.wav`, where
   `<reference>` is the video id (its own speaker) or `fixed_es`, plus
   `audio/out/<name>/stats.json` (`load_s`, `peak_vram_gb`, `clips` with `gen_s`
   and `audio_s`). For (B), `audio/fit/<name>/fit.json` (see `gen_indextts.py`).
3. `uv run docs/bench/run.py <name>`.

## Generators

| Script | Runs in | Writes |
|---|---|---|
| `prep.py` | OpenDub's env | references and the edge-tts baseline |
| `gen_qwen.py` | a venv with `qwen-tts` | `audio/out/qwen3` |
| `gen_chatterbox.py v3\|es_es` | a venv with `chatterbox-tts` (GitHub commit 5de7a54) | `audio/out/chatterbox_*` |
| `gen_indextts.py` | the IndexTTS venv (`setup-indextts`), from its repo | `audio/out/indextts`, `audio/fit/indextts` |
| `alt_refs.py` | OpenDub's env | alternative references of one speaker (8–12 s, continuous, least music) |
| `gen_alt_refs.py` | the IndexTTS venv | one clip set per alternative reference |
| `ref_texts.py` | OpenDub's env | transcripts of the dub references (`audio/fit/*_clone_ref.txt`) |
| `gen_cosyvoice.py` | a CosyVoice venv, from its repo | `audio/out/cosyvoice3`, `audio/fit/cosyvoice3` |
| `gen_voxcpm.py` | a venv with `voxcpm` | `audio/out/voxcpm2`, `audio/fit/voxcpm2` |
| `gen_fish.py` | a fish-speech venv, from its repo | `audio/out/fish_s2` (does not fit in 16 GB) |

`common.py` is the loop the last three share: a generator only loads its model
and says how it speaks one sentence (and whether it has a native speed control,
which (B) then uses like IndexTTS's `duration_factor`). The venvs used for them,
with PyTorch 2.8 + CUDA 12.8, are made by `setup.sh` scripts under
`work/_bench/<engine>/`; install them with `uv pip install --no-config`, or the
overrides in OpenDub's `pyproject.toml` leak into them.

## Whole dubs

`dub_metrics.py` measures a kept version as it is heard, the final MP4: fit
(sped up, not fitting, shortened, edge-tts), delays and drift from the mix's own
placement, loudness and true peak, and whisper small's CER and p_es over each
clip's stretch of the mixed track (with the music under it). One JSON per
version in `results/dubs/`.

```bash
uv run python docs/bench/dub_metrics.py 17kBVfGjI8c rwF-X5STYks KS837a-TFRc   # latest version of each
uv run python docs/bench/dub_metrics.py KS837a-TFRc/20261025-141750-chatterbox # one version
```

The committed set (25 Oct 2026), Chatterbox V3 against the es-ES finetune on the
listening corpus, and the long video before and after loudness normalization:

| Video | Version | Clips | Sped up | Not fitting | Voice > 0.5 s late | LUFS | True peak | CER | p_es |
|---|---|---|---|---|---|---|---|---|---|
| 17kBVfGjI8c (2 min) | V3 | 24 | 1 | 0 | 0 s | −16.0 | −1.5 | 0.016 | 0.95 |
| | es-ES | 24 | 2 | 0 | 0 s | −16.0 | −1.8 | 0.004 | 0.98 |
| rwF-X5STYks (2 min) | V3 | 17 | 8 | 0 | 0 s | −16.0 | −1.6 | 0.008 | 0.99 |
| | es-ES | 17 | 10 | 0 | 0 s | −16.0 | −1.9 | 0.001 | 0.98 |
| VD6xJq8NguY (11 min, music) | V3 | 111 | 57 | 3 | 46 s | −16.0 | −1.9 | 0.011 | 0.95 |
| | es-ES | 111 | 55 | 6 | 62 s | −16.0 | −2.0 | 0.015 | 0.94 |
| 7mCTaTJ0kDo (20 min, fast) | V3 | 228 | 69 | 6 | 33 s | −16.0 | −1.7 | 0.016 | 0.95 |
| | es-ES | 228 | 75 | 9 | 43 s | −16.0 | −2.3 | 0.018 | 0.97 |
| KS837a-TFRc (19 min) | before T-07 | 199 | 46 | 1 | 0 s | −26.6 | −1.5 | 0.031 | 0.92 |
| | after T-07 | 199 | 46 | 1 | 0 s | −16.3 | −1.5 | 0.030 | 0.93 |

Normalizing the loudness moved the long video from −26.6 to −16.3 LUFS and left
everything else as it was (same clips, same peak, CER within noise). The es-ES
finetune is a little longer-winded: more clips sped up or not fitting and more
voice heard late on the fast videos; intelligibility is the same within noise.
Which one sounds better is for the blind listening (`listening/`).

## Shortening

`shortening.py` asks Claude (Sonnet, fixed rubric) whether each sentence the voice
phase shortened to fit its slot still says what its full translation said:
**kept** (only wording or filler went), **nuanced** (a detail went, the point
stays) or **lost** (the meaning changed or something needed went). Only versions
that record the translation they were made from count. The verdicts and their
reasons are in `results/shortening.json`; the sentences themselves stay in
`work/_bench/`, as they are third-party content.

```bash
uv run python docs/bench/shortening.py KS837a-TFRc h7PA4mXE_GA 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo
```

On the six videos (25 Oct 2026), 58 shortened sentences, 70 → 55 characters on average:

| Engine | Shortened | Kept | Nuanced | Lost |
|---|---|---|---|---|
| Chatterbox V3 | 42 | 25 (60%) | 15 (36%) | 2 (5%) |
| Chatterbox es-ES | 15 | 8 (53%) | 7 (47%) | 0 |
| CosyVoice | 1 | 1 | 0 | 0 |

Typical nuances: a conditional dropped ("if you're interested"), a colourful verb
made plain, an obligation turned into a statement. The two losses are both on the
three-speaker interview: a "I thought" that became "he said", and a two-word
fragment cut down to "and". 2 losses in 58 (3%), none on the single-speaker videos:
no reason to change the shortening prompt for now; worth measuring again if the
losses grow with several voices, where a changed subject also changes who speaks.

## Translation fidelity

`fidelity.py` has a model other than the translator (Opus judges Sonnet) rate each
sentence of the dub's translation against its original, the sentence before it given as
context:
- **meaning:** kept, nuanced or lost;
- **technical terms:** ok, wrong or none.

The translation is the one the dub speaks, made to fit each slot, so what it drops to fit
counts against it. Short videos are judged whole, longer ones on 60 sentences drawn with a
fixed seed; hand edits are skipped. Results per translator and video are in
`results/fidelity.json`, without the sentences. T-28 sets a local model against Sonnet
with it (`--file`, `--translator`).

```bash
uv run python docs/bench/fidelity.py 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo KS837a-TFRc R4zlpwwEpnY
```

Sonnet 5.5's translations on six videos (26 Oct 2026), 281 sentences:

| Video | Judged | Kept | Nuanced | Lost | Terms wrong |
|---|---|---|---|---|---|
| 17kBVfGjI8c (2 min) | 24 | 24 | 0 | 0 | 0 of 13 |
| rwF-X5STYks (2 min) | 17 | 17 | 0 | 0 | 0 of 12 |
| VD6xJq8NguY (11 min, music) | 60 | 53 | 7 | 0 | 0 of 24 |
| 7mCTaTJ0kDo (20 min, fast) | 60 | 57 | 3 | 0 | 0 of 28 |
| KS837a-TFRc (19 min) | 60 | 58 | 2 | 0 | 1 of 24 |
| R4zlpwwEpnY (23 min, two voices) | 60 | 57 | 3 | 0 | 0 of 15 |
| **All** | **281** | **266 (95%)** | **15 (5%)** | **0** | **1 of 116** |

No sentence loses its meaning, one in twenty loses a nuance to fit its slot, and the one
wrong term is animation jargon ("aftermath" as «secuelas»). The judge is another model of
the same family as the translator, which may share its blind spots; it measures, it
doesn't certify.

## Local translators

`translators.py` (T-28) translates the corpus with each translator exactly as a dub would
(blocks of 30, the previous context, each sentence's budget at the pace of the voice that
would speak it), on a copy of each video's folder, and writes time, length and budget
overruns to `results/translators.json`. `fidelity.py --file` then judges each one.

```bash
uv run python docs/bench/translators.py 17kBVfGjI8c rwF-X5STYks VD6xJq8NguY 7mCTaTJ0kDo KS837a-TFRc R4zlpwwEpnY \
    --translator cli:claude-sonnet-5-5 --translator ollama:qwen3.6:35b-a3b-coding --translator ollama:gemma3:27b
```

Six videos (26 Oct 2026), RTX 5080 16 GB, models at Q4_K_M:

| | Sonnet 5.5 | Qwen3.6-35B-A3B | Gemma 3 27B |
|---|---|---|---|
| Fits in 16 GB | — | MoE, 3B active | no: 23% in RAM |
| Time, six videos | 310 s | 381 s | 3,713 s, and failed the podcast |
| Spanish/original length | 0.85–0.98 | 0.77–1.07 | 1.00–1.12 |
| Over budget / over 1.25× | 180 / 36 of 764 | 216 / 69 of 764 | (five videos) 316 / 118 of 579 |
| Meaning kept · nuanced · lost (281) | 271 · 8 · 2 | 244 · 30 · 7 | (221) 205 · 12 · 4 |
| Terms wrong | 3 of 118 | 5 of 112 | 8 of 108 |

Dubbed with Chatterbox (`dub_metrics.py --work`, the same pace and rules):

| | Sonnet | Qwen |
|---|---|---|
| Two short videos: shortened · not fitting · late voice | 0 · 0 · 0 s | 1 · 1 · 14 s |
| `VD6xJq8NguY` (11 min): shortened · not fitting | 7 · 3 | 16 · 6 |
| `VD6xJq8NguY`: late voice · mean delay | 46 s · 0.16 s | 168 s · 0.31 s |

- **Gemma 3 27B is out:** it doesn't fit the GPU, takes twelve times as long, ignores the
  budget (10% longer than the original) and lost the ids of a block three times running.
- **Qwen3.6-35B-A3B works** and is nearly as fast as Sonnet, but it drops more nuances
  and overshoots its budget twice as often, which the voice phase pays for. It is the
  default of `--backend ollama`; Sonnet stays the default translator.
- Gemma 3 12B and Qwen3 14B, which fit the GPU, were not tried: Qwen3.6, a mixture of
  experts, already runs at Sonnet's speed, so speed doesn't call for them.

## F5-TTS in Spanish (discarded, 26 Oct 2026)

jpgallegoar/F5-Spanish (F5-TTS's base finetuned on 218 h of Spanish, CC-BY-NC-4.0) was
wired in as an experimental engine and dubbed both short videos. It was light (1.9 GB of
VRAM, half a second per second of speech), fitted every clip natively and whisper heard
its clips as Spanish (0.99), but heard blind (`listening/results/f5-taste.json`, 10
fragments, against IndexTTS and Chatterbox) it came last in every fragment:

| | Mean | Preferred |
|---|---|---|
| Chatterbox | 3.6 | 6 (all five of the male voice) |
| IndexTTS | 3.0 | 4 (four of five of the female voice) |
| F5-TTS | 2.4 | 0 |

The engine and its venv were removed. The other suggestions of that round: Qwen3-TTS was
already discarded for its accent (Phase C), GPT-SoVITS has no Spanish, OpenVoice speaks a
base Spanish voice with the speaker's timbre rather than cloning, and Chatterbox Turbo is
English only.

## Audio

`audio/` holds the reference cuts (from the original videos), the generated
voices and the listening files (`audio/listen/`). It is **not committed**: the
repository is public and those are excerpts of third-party videos and cloned
voices of real people. Keep it locally; the results in `results/` are enough to
compare a new model.
