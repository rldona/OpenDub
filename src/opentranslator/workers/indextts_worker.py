"""IndexTTS worker: runs inside IndexTTS's own venv (Python 3.11), not OpenTranslator's.

It must stay self-contained (standard library, torch and indextts only), since
OpenTranslator is not installed in that venv. Protocol, one JSON object per line:

    worker → {"ready": true, "device": "...", "load_s": 12.3}
    client → {"id": 1, "text": "...", "ref": "/abs/ref.wav", "out": "/abs/out.wav",
              "lang": "ES", "duration_factor": 1.0, "seed": 0}
    worker → {"id": 1, "ok": true, "seconds": 2.1} or {"id": 1, "ok": false, "error": "..."}

stdout carries only the protocol: IndexTTS prints progress to stdout, so file
descriptor 1 is pointed at stderr and the protocol gets a private copy of it.
The worker exits when stdin closes.
"""

import json
import os
import sys
import time
import traceback


def main() -> None:
    protocol = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    model_dir = sys.argv[1]
    t0 = time.monotonic()
    import torch
    from indextts.infer_v2_5 import IndexTTS2

    tts = IndexTTS2(cfg_path=os.path.join(model_dir, "config.yaml"), model_dir=model_dir,
                    use_bf16=torch.cuda.is_available())
    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    protocol.write(json.dumps({"ready": True, "device": device, "load_s": round(time.monotonic() - t0, 1)}) + "\n")

    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            t = time.monotonic()
            torch.manual_seed(req.get("seed", 0))
            tmp = req["out"] + ".part.wav"
            tts.infer(spk_audio_prompt=req["ref"], text=req["text"], lang=req.get("lang", "ES"),
                      output_path=tmp, duration_factor=req.get("duration_factor", 1.0))
            os.replace(tmp, req["out"])
            reply = {"id": req["id"], "ok": True, "seconds": round(time.monotonic() - t, 2)}
        except Exception as e:  # report and keep serving: one bad sentence must not kill the worker
            traceback.print_exc()
            reply = {"id": req["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
        protocol.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
