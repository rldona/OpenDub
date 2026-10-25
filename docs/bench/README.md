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

## Audio

`audio/` holds the reference cuts (from the original videos), the generated
voices and the listening files (`audio/listen/`). It is **not committed**: the
repository is public and those are excerpts of third-party videos and cloned
voices of real people. Keep it locally; the results in `results/` are enough to
compare a new model.
