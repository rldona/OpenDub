"""CosyVoice worker: runs inside CosyVoice's own venv (Python 3.11), not OpenTranslator's.

It must stay self-contained (standard library, torch, soundfile and CosyVoice's
repo only), since OpenTranslator is not installed in that venv. It runs with
the CosyVoice repo as its working directory. Protocol, one JSON object per line:

    worker → {"ready": true, "device": "...", "load_s": 9.0, "sample_rate": 24000}
    client → {"id": 1, "text": "...", "ref": "/abs/ref.wav", "out": "/abs/out.wav",
              "duration_factor": 1.0, "seed": 0}
    worker → {"id": 1, "ok": true, "seconds": 1.4} or {"id": 1, "ok": false, "error": "..."}

Cross-lingual cloning (the reference audio, no transcript); duration_factor is
passed as CosyVoice's speed (1/factor). Clips are written as 16-bit PCM: CosyVoice
saves float WAVs, which the pipeline's wave reader doesn't take.

stdout carries only the protocol: CosyVoice logs to stdout too, so file
descriptor 1 is pointed at stderr and the protocol gets a private copy of it.
The worker exits when stdin closes.
"""

import json
import os
import sys
import time
import traceback

PREFIX = "You are a helpful assistant.<|endofprompt|>"  # CosyVoice 3's system prompt


def main() -> None:
    protocol = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    model_dir = sys.argv[1]
    sys.path[:0] = [os.getcwd(), os.path.join(os.getcwd(), "third_party", "Matcha-TTS")]
    t0 = time.monotonic()
    import soundfile as sf
    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    model = AutoModel(model_dir=model_dir)
    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    protocol.write(json.dumps({"ready": True, "device": device, "sample_rate": model.sample_rate,
                               "load_s": round(time.monotonic() - t0, 1)}) + "\n")

    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            t = time.monotonic()
            torch.manual_seed(req.get("seed", 0))
            speed = 1.0 / req.get("duration_factor", 1.0)
            chunks = model.inference_cross_lingual(PREFIX + req["text"], req["ref"], stream=False, speed=speed,
                                                   text_frontend=False)
            audio = torch.cat([c["tts_speech"] for c in chunks], dim=1).squeeze(0).cpu().numpy()
            tmp = req["out"] + ".part.wav"
            sf.write(tmp, audio, model.sample_rate, subtype="PCM_16")
            os.replace(tmp, req["out"])
            reply = {"id": req["id"], "ok": True, "seconds": round(time.monotonic() - t, 2)}
        except Exception as e:  # report and keep serving: one bad sentence must not kill the worker
            traceback.print_exc()
            reply = {"id": req["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
        protocol.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
