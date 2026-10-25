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
