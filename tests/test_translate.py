import json

import pytest

from opentranslator import translate
from opentranslator.config import Settings
from opentranslator.models import Segment, load_segments, save_segments
from opentranslator.workdir import WorkDir


def _segments(n: int) -> list[Segment]:
    return [Segment(id=i + 1, start=i * 3.0, end=i * 3.0 + 2.0, text=f"Sentence {i + 1}.") for i in range(n)]


@pytest.fixture
def wd(tmp_path):
    wd = WorkDir(tmp_path, "vid")
    wd.meta.write_text(json.dumps({"language": "en"}))
    save_segments(wd.segments, _segments(7))
    return wd


def test_slot_borrows_at_most_one_second_of_silence():
    segs = [Segment(1, 0.0, 2.0, "a"), Segment(2, 2.5, 4.0, "b"), Segment(3, 10.0, 11.0, "c")]
    assert translate._slot(segs, 0) == 2.5
    assert translate._slot(segs, 1) == 2.5
    assert translate._slot(segs, 2) == 2.0


def test_user_prompt_includes_limits_and_context():
    seg = Segment(4, 0.0, 2.0, "Hello there.")
    data = json.loads(translate._user_prompt([(seg, 2.0)], [("Hi.", "Hola.")], 15.0))
    assert data["contexto_previo"] == [{"original": "Hi.", "traduccion": "Hola."}]
    assert data["segmentos"] == [{"id": 4, "duracion_s": 2.0, "max_chars": 30, "texto": "Hello there."}]


def test_run_translates_in_blocks_with_context(wd, monkeypatch):
    calls = []

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        calls.append(data)
        return {"segments": [{"id": s["id"], "text": f"Frase {s['id']}."} for s in data["segmentos"]]}, 0.01

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    result = translate.run(wd, Settings(batch_size=3, chars_per_second=15))
    assert [len(c["segmentos"]) for c in calls] == [3, 3, 1]
    assert "contexto_previo" not in calls[0]
    assert calls[1]["contexto_previo"][-1] == {"original": "Sentence 3.", "traduccion": "Frase 3."}
    assert [s.text for s in result] == [f"Frase {i}." for i in range(1, 8)]
    assert result[0].start == 0.0 and result[0].end == 2.0
    assert load_segments(wd.translation) == result


def test_run_retries_when_ids_mismatch(wd, monkeypatch):
    attempts = {"n": 0}

    def flaky_cli(system, prompt, model):
        attempts["n"] += 1
        segs = json.loads(prompt)["segmentos"]
        if attempts["n"] == 1:
            segs = segs[:-1]  # one segment missing
        return {"segments": [{"id": s["id"], "text": "x"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", flaky_cli)
    translate.run(wd, Settings(batch_size=10, chars_per_second=15))
    assert attempts["n"] == 2


def test_run_resumes_from_saved_blocks_and_caches(wd, monkeypatch):
    def failing_after_first(system, prompt, model):
        segs = json.loads(prompt)["segmentos"]
        if segs[0]["id"] > 1:
            raise RuntimeError("crash")
        return {"segments": [{"id": s["id"], "text": "ok"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", failing_after_first)
    with pytest.raises(SystemExit):
        translate.run(wd, Settings(batch_size=4, chars_per_second=15))

    seen = []

    def ok_cli(system, prompt, model):
        segs = json.loads(prompt)["segmentos"]
        seen.extend(s["id"] for s in segs)
        return {"segments": [{"id": s["id"], "text": "bien"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", ok_cli)
    result = translate.run(wd, Settings(batch_size=4, chars_per_second=15))
    assert seen == [5, 6, 7]  # the first block comes from disk
    assert [s.text for s in result] == ["ok"] * 4 + ["bien"] * 3

    monkeypatch.setattr(translate, "_call_cli", lambda *a: pytest.fail("should not be called"))
    translate.run(wd, Settings(batch_size=4, chars_per_second=15))


def test_shorten_sends_limits_and_returns_texts(monkeypatch):
    seen = {}

    def fake_cli(system, prompt, model):
        seen["system"], seen["items"] = system, json.loads(prompt)
        return {"segments": [{"id": 3, "text": "Corta."}]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    got = translate.shorten([(3, "Original long text.", "Traducción demasiado larga.", 12)], "es-ES-AlvaroNeural", Settings())
    assert got == {3: "Corta."}
    assert seen["items"] == [{"id": 3, "original": "Original long text.", "traduccion": "Traducción demasiado larga.", "max_chars": 12}]
    assert "español de España" in seen["system"]


def test_run_uses_calibrated_rate_when_not_given(wd, monkeypatch):
    from opentranslator import tts

    monkeypatch.setattr(tts, "speaking_rate", lambda root, voice, rate: 20.0)
    prompts = []

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        prompts.append(data)
        return {"segments": [{"id": s["id"], "text": "x"} for s in data["segmentos"]]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    translate.run(wd, Settings(batch_size=10))
    # first segment: 3 s slot (2 s long + 1 s borrowed) at 20 chars/s
    assert prompts[0]["segmentos"][0]["max_chars"] == 60
