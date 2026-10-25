"""Fish Audio S2 Pro (Fish Audio Research License): (A) the test sentences and (B) the dub segments.

In-context cloning from the reference audio and its transcript, with the
library's default sampling. The weights take ~11 GB; its KV cache, sized for the
model's 32k-token context, would take 4.8 GB more and not fit in 16 GB, so it is
sized for MAX_SEQ_LEN tokens (a 15 s reference, its text and a long sentence
stay under ~1,000). No numeric speed control, so (B) measures the
natural duration only. Run with its venv, from its repo (work/_bench/fish_s2/repo):

    .venv/bin/python -I <this file> [name]
"""
import sys
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

sys.path.insert(0, ".")
import fish_speech.models.text2semantic.inference as t2s  # noqa: E402
from fish_speech.utils.schema import ServeReferenceAudio, ServeTTSRequest  # noqa: E402
from tools.server.model_manager import ModelManager  # noqa: E402

MAX_SEQ_LEN = 4096
_init_model = t2s.init_model


def init_model(*args, **kwargs):
    model, decode_one_token = _init_model(*args, **kwargs)
    model.config.max_seq_len = MAX_SEQ_LEN
    return model, decode_one_token


t2s.init_model = init_model

NAME = sys.argv[1] if len(sys.argv) > 1 else "fish_s2"

t0 = time.monotonic()
manager = ModelManager(mode="tts", device="cuda", half=False, compile=False,
                       llama_checkpoint_path="checkpoints/s2-pro",
                       decoder_checkpoint_path="checkpoints/s2-pro/codec.pth",
                       decoder_config_name="modded_dac_vq")
engine = manager.tts_inference_engine
load_s = time.monotonic() - t0
print(f"loaded in {load_s:.1f}s", flush=True)
sample_rate = None


def synth(text: str, ref: Path, ref_text: str, out: Path, factor: float) -> None:
    global sample_rate
    req = ServeTTSRequest(text=text, references=[ServeReferenceAudio(audio=ref.read_bytes(), text=ref_text)],
                          seed=common.SEED, normalize=False)
    for result in engine.inference(req):
        if result.code == "error":
            raise result.error
        if result.code == "final":
            sample_rate, audio = result.audio
            sf.write(str(out), audio, sample_rate)


common.warm_up(synth)
common.sentences(NAME, synth, load_s, {"sample_rate": sample_rate, "max_seq_len": MAX_SEQ_LEN})
common.fit(NAME, synth, native_speed=False)
