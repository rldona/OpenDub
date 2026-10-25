"""One process on the GPU at a time (gpu.hold): the other waits, can be cancelled, and gets a free GPU."""

import subprocess
import sys
import threading
import time

import pytest

from opendub import gpu, log

HOLDS = """
import sys, time
from opendub import gpu
with gpu.hold("dub other"):
    print("held", flush=True)
    time.sleep(float(sys.argv[1]))
"""


def _other_process(seconds: float) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-c", HOLDS, str(seconds)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_a_second_process_waits_for_the_gpu_and_says_who_has_it(monkeypatch, caplog):
    monkeypatch.setattr(gpu, "POLL_S", 0.05)
    other = _other_process(0.6)
    assert "dub other" in gpu.holder()
    released = []
    start = time.monotonic()
    with gpu.hold("dub mine", on_release=lambda: released.append(1)):
        waited = time.monotonic() - start
        assert "dub mine" in gpu.holder()
        with gpu.hold("a phase inside"):  # nested in the same process: no wait, no release
            pass
        assert released == []
    other.wait()
    assert waited > 0.3 and released == [1] and gpu.holder() is None
    assert "Waiting for the GPU" in caplog.text and "dub other" in caplog.text


def test_waiting_for_the_gpu_can_be_cancelled(monkeypatch):
    monkeypatch.setattr(gpu, "POLL_S", 0.05)
    other = _other_process(5)
    try:
        threading.Timer(0.3, log.request_cancel).start()
        with pytest.raises(log.Cancelled):
            with gpu.hold("dub mine"):
                pytest.fail("got the GPU while another process had it")
    finally:
        log.clear_cancel()
        other.kill()
        other.wait()
    with gpu.hold("dub mine"):  # once the other one is gone, it's free
        pass


def test_the_memory_is_freed_even_when_the_dub_fails():
    released = []
    with pytest.raises(RuntimeError):
        with gpu.hold("dub", on_release=lambda: released.append(1)):
            raise RuntimeError("the voice phase failed")
    assert released == [1] and gpu.holder() is None
