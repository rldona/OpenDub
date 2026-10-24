import pytest


@pytest.fixture(autouse=True)
def no_real_synthesis(monkeypatch):
    """Tests must never reach a real voice engine (GPU, model downloads, a running dub)."""
    from opentranslator import clone, indextts

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to synthesize with a real engine; patch tts._render_jobs")

    monkeypatch.setattr(indextts, "synthesize", refuse)
    monkeypatch.setattr(clone, "synthesize", refuse)
