"""Chatterbox worker: one of the processes that speak Chatterbox clips side by side.

Unlike the IndexTTS and CosyVoice workers it runs with OpenDub's own venv (Chatterbox
is installed there, the `clone` extra) and reuses clone.synthesize. Same protocol
(engines.py), one JSON object per line:

    worker → {"ready": true, "device": "...", "load_s": 9.1}
    client → {"id": 1, "text": "...", "ref": "/abs/ref.wav", "out": "/abs/out.wav", "seed": 0, ...}
    worker → {"id": 1, "ok": true, "seconds": 1.2} or {"id": 1, "ok": false, "error": "..."}

stdout carries only the protocol: file descriptor 1 is pointed at stderr and the
protocol gets a private copy of it. The worker exits when stdin closes.
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path


def main() -> None:
    protocol = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    t0 = time.monotonic()
    from opendub import clone

    clone._load()
    import torch

    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else clone._device()
    protocol.write(json.dumps({"ready": True, "device": device, "load_s": round(time.monotonic() - t0, 1)}) + "\n")

    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            t = time.monotonic()
            clone.synthesize(req["text"], Path(req["ref"]), req.get("seed", 0), Path(req["out"]))
            reply = {"id": req["id"], "ok": True, "seconds": round(time.monotonic() - t, 2)}
        except Exception as e:  # report and keep serving: one bad sentence must not kill the worker
            traceback.print_exc()
            reply = {"id": req["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}
        protocol.write(json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
