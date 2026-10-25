# Diarization benchmark

Which open diarizer tells best who speaks each sentence, for dubbing videos with
several voices (results and decision in [../../v2-plan.md](../../v2-plan.md#several-voices)).

Candidates, each in its own venv under `work/_bench/diarize/<name>/` (PyTorch 2.8 +
CUDA 12.8, installed with `uv pip install --no-config`):

| Model | License | Install |
|---|---|---|
| pyannote community-1 | CC-BY-4.0, gated on Hugging Face (`HF_TOKEN`) | `pyannote.audio` 4.0.7 |
| NVIDIA Nemotron 3 Diarization | OpenMDW 1.1 (commercial use allowed), up to 8 speakers | NeMo from `NVIDIA-NeMo/Speech` commit `68a12fc` (PyPI's 3.0.0 can't load it) |

DiariZen was left out: its weights are CC BY-NC 4.0.

```bash
work/_bench/diarize/<model>/.venv/bin/python docs/bench/diarize/run_<model>.py <audio> <out.json>
uv run python docs/bench/diarize/synth.py                    # conversations with a known answer
uv run python docs/bench/diarize/score.py                    # scores every run in work/_bench/diarize/out
uv run python docs/bench/diarize/real_checks.py <video id>   # checks on a real video without labels
uv run python docs/bench/diarize/label.py <video id>...      # hand labels, if someone can listen
```

## What is measured

- **Synthetic conversations** (`synth.py`): turns of real speech of three distinct
  people taken from the single-voice videos (two men of nearly the same pitch,
  120 and 123 Hz, and a woman), alternated with pauses and, in the panel, overlaps.
  Who says each sentence is known exactly. Every turn is brought to the same
  loudness over one music bed, so the speakers aren't told apart by loudness;
  they still come from different recordings, which makes it easier than real.
- **A real interview** (`real_checks.py`, three people, 70 min) without labels:
  whether each sentence's own pitch agrees with the gender of the speaker it is
  given (catches man↔woman mix-ups), and how often the two models agree.
- **Single-voice controls**: the five videos of one speaker, where any second
  voice is a false split. What counts for a dub is how many sentences would get it.
- **Speed and VRAM** of each run.

`results/` keeps the scores; the audio, labels and runs stay in `work/` (third-party
voices, not committed).
