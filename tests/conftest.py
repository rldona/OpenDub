import pytest


@pytest.fixture(autouse=True)
def no_real_synthesis(monkeypatch):
    """Tests must never reach a real voice engine (GPU, model downloads, a running dub)."""
    from opendub import clone, cosyvoice, indextts

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to synthesize with a real engine; patch tts._render_jobs")

    monkeypatch.setattr(indextts, "synthesize", refuse)
    monkeypatch.setattr(cosyvoice, "synthesize", refuse)
    monkeypatch.setattr(clone, "pool_size", lambda: 1)  # no Chatterbox worker processes either
    monkeypatch.setattr(clone, "synthesize", refuse)


@pytest.fixture(autouse=True)
def no_real_style(monkeypatch, tmp_path_factory):
    """Settings() defaults to work/ in the repo: tests must not pick up the user's work/style.json."""
    from opendub import style

    real = style.load
    empty = tmp_path_factory.mktemp("no-style")
    monkeypatch.setattr(style, "load", lambda root, *a, **k: real(empty if root == style.Path("work") else root, *a, **k))


@pytest.fixture(autouse=True)
def no_network_probe(monkeypatch):
    """The Claude reachability check opens a socket: tests never do (test_network_errors checks it)."""
    from opendub import translate

    monkeypatch.setattr(translate, "_reachable", True)


@pytest.fixture(autouse=True)
def own_gpu_lock(monkeypatch, tmp_path_factory):
    """The GPU lock is machine-wide (~/.cache/opendub): tests use their own, or a real dub would block them."""
    monkeypatch.setenv("OPENDUB_GPU_LOCK", str(tmp_path_factory.mktemp("gpu") / "gpu.lock"))
