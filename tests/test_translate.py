import json

import pytest

from opendub import translate
from opendub.config import Settings
from opendub.models import Segment, load_segments, save_segments
from opendub.tts import Pace
from opendub.workdir import WorkDir


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
    data = json.loads(translate._user_prompt([(seg, 2.0)], [("Hi.", "Hola.")], Pace(15.0)))
    assert data["previous_context"] == [{"original": "Hi.", "translation": "Hola."}]
    assert data["segments"] == [{"id": 4, "duration_s": 2.0, "max_chars": 30, "text": "Hello there."}]


def test_run_translates_in_blocks_with_context(wd, monkeypatch):
    calls = []

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        calls.append(data)
        return {"segments": [{"id": s["id"], "text": f"Frase {s['id']}."} for s in data["segments"]]}, 0.01

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    result = translate.run(wd, Settings(batch_size=3, chars_per_second=15))
    assert [len(c["segments"]) for c in calls] == [3, 3, 1]
    assert "previous_context" not in calls[0]
    assert calls[1]["previous_context"][-1] == {"original": "Sentence 3.", "translation": "Frase 3."}
    assert [s.text for s in result] == [f"Frase {i}." for i in range(1, 8)]
    assert result[0].start == 0.0 and result[0].end == 2.0
    assert load_segments(wd.translation) == result


def test_run_retries_when_ids_mismatch(wd, monkeypatch):
    attempts = {"n": 0}

    def flaky_cli(system, prompt, model):
        attempts["n"] += 1
        segs = json.loads(prompt)["segments"]
        if attempts["n"] == 1:
            segs = segs[:-1]  # one segment missing
        return {"segments": [{"id": s["id"], "text": "x"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", flaky_cli)
    translate.run(wd, Settings(batch_size=10, chars_per_second=15))
    assert attempts["n"] == 2


def test_run_resumes_from_saved_blocks_and_caches(wd, monkeypatch):
    def failing_after_first(system, prompt, model):
        segs = json.loads(prompt)["segments"]
        if segs[0]["id"] > 1:
            raise RuntimeError("crash")
        return {"segments": [{"id": s["id"], "text": "ok"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", failing_after_first)
    with pytest.raises(SystemExit):
        translate.run(wd, Settings(batch_size=4, chars_per_second=15))

    seen = []

    def ok_cli(system, prompt, model):
        segs = json.loads(prompt)["segments"]
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
    assert seen["items"] == [{"id": 3, "original": "Original long text.", "translation": "Traducción demasiado larga.", "max_chars": 12}]
    assert "Castilian Spanish (Spain)" in seen["system"]


def test_shorten_drops_garbled_versions(monkeypatch):
    def fake_cli(system, prompt, model):
        return {"segments": [{"id": 1, "text": "Err\ufffd\ufffd."}, {"id": 3, "text": "Corta."}]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    items = [(i, "Original.", "Traducción larga.", 10) for i in (1, 3)]
    assert translate.shorten(items, "es-ES-AlvaroNeural", Settings()) == {3: "Corta."}


def test_run_uses_calibrated_rate_when_not_given(wd, monkeypatch):
    from opendub import tts

    monkeypatch.setattr(tts, "speaking_rate", lambda root, voice, rate: 20.0)
    prompts = []

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        prompts.append(data)
        return {"segments": [{"id": s["id"], "text": "x"} for s in data["segments"]]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    translate.run(wd, Settings(batch_size=10))
    # first segment: 3 s slot (2 s long + 1 s borrowed) at 20 chars/s
    assert prompts[0]["segments"][0]["max_chars"] == 60


def _style(wd, data, where="video"):
    from opendub import style

    path = (wd.path if where == "video" else wd.path.parent) / style.FILE
    path.write_text(json.dumps(data))


def test_style_sends_register_notes_and_only_the_block_terms(wd, monkeypatch):
    _style(wd, {"terms": [{"source": "itch store", "target": ""}, {"source": "Sentence 1", "target": "Frase uno"},
                          {"source": "never said", "target": "x"}]}, where="global")
    _style(wd, {"register": "usted", "notes": "Pixel art channel."})
    calls = []

    def fake_cli(system, prompt, model):
        data = json.loads(prompt)
        calls.append((system, data))
        return {"segments": [{"id": s["id"], "text": "ok"} for s in data["segments"]]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    translate.run(wd, Settings(work_root=wd.path.parent, batch_size=3, chars_per_second=15))
    (system1, first), (system2, second), _ = calls
    assert first["glossary"] == [{"term": "Sentence 1", "translation": "Frase uno"}]
    assert "glossary" not in second
    assert "usted (formal)" in system1 and "Pixel art channel." in system1
    assert "`glossary`" in system1 and "`glossary`" not in system2


def test_style_change_retranslates_only_blocks_with_the_new_term(wd, monkeypatch):
    seen = []

    def fake_cli(system, prompt, model):
        segs = json.loads(prompt)["segments"]
        seen.append([s["id"] for s in segs])
        return {"segments": [{"id": s["id"], "text": "ok"} for s in segs]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    settings = Settings(work_root=wd.path.parent, batch_size=3, chars_per_second=15)
    translate.run(wd, settings)
    assert len(seen) == 3
    _style(wd, {"terms": [{"source": "Sentence 5", "target": "Frase cinco"}]})
    seen.clear()
    translate.run(wd, settings)
    assert seen == [[4, 5, 6]]
    translate.run(wd, settings)  # cached as a whole now
    assert seen == [[4, 5, 6]]


def test_a_term_the_video_never_says_keeps_the_cache(wd, monkeypatch):
    monkeypatch.setattr(translate, "_call_cli", lambda system, prompt, model: (
        {"segments": [{"id": s["id"], "text": "ok"} for s in json.loads(prompt)["segments"]]}, 0.0))
    settings = Settings(work_root=wd.path.parent, batch_size=3, chars_per_second=15)
    translate.run(wd, settings)
    _style(wd, {"terms": [{"source": "elsewhere", "target": "x"}]})
    monkeypatch.setattr(translate, "_call_cli", lambda *a: pytest.fail("should not be called"))
    translate.run(wd, settings)


def test_style_variant_sets_the_target_and_the_voice(wd, monkeypatch):
    from opendub import style

    _style(wd, {"variant": "latam"})
    systems = []
    monkeypatch.setattr(translate, "_call_cli", lambda system, prompt, model: systems.append(system) or (
        {"segments": [{"id": s["id"], "text": "ok"} for s in json.loads(prompt)["segments"]]}, 0.0))
    settings = Settings(work_root=wd.path.parent, batch_size=10, chars_per_second=15)
    translate.run(wd, settings)
    assert "neutral Latin American Spanish" in systems[0]
    st = style.load(wd.path.parent, wd.path)
    assert style.with_variant_voice(settings, st).voice == "es-MX-JorgeNeural"
    assert style.with_variant_voice(Settings(voice="es-AR-TomasNeural"), st).voice == "es-AR-TomasNeural"


def test_shorten_keeps_the_glossary(monkeypatch):
    from opendub import style

    seen = {}

    def fake_cli(system, prompt, model):
        seen["system"], seen["payload"] = system, json.loads(prompt)
        return {"segments": [{"id": 3, "text": "Corta."}]}, 0.0

    monkeypatch.setattr(translate, "_call_cli", fake_cli)
    st = style.Style(register="tu", terms=[style.Term("itch store")])
    translate.shorten([(3, "Buy it on my itch store.", "Cómpralo en mi itch store, que está genial.", 30)],
                      "es-ES-AlvaroNeural", Settings(), st)
    assert seen["payload"]["glossary"] == [{"term": "itch store", "translation": ""}]
    assert seen["payload"]["items"][0]["id"] == 3
    assert "tú (informal)" in seen["system"]


def test_style_files_merge_and_check():
    from opendub import style

    base = style.parse({"register": "tu", "terms": [{"source": "VFX", "target": ""}, {"source": "slash", "target": "corte"}],
                        "notes": "a"})
    over = style.parse({"variant": "es-ES", "terms": [{"source": "Slash", "target": "tajo"}], "notes": "b"})
    st = style.merge(base, over)
    assert (st.register, st.variant, st.notes) == ("tu", "es-ES", "a\nb")
    assert [(t.source, t.target) for t in st.terms] == [("VFX", ""), ("Slash", "tajo")]
    assert style.matching(st.terms, ["the slash itself"]) == [st.terms[1]]
    assert style.matching(st.terms, ["slashing"]) == []  # whole words only
    assert style.misses(st.terms, "Add the VFX slash.", "Añade los VFX del tajo.") == []
    assert [t.source for t in style.misses(st.terms, "Add the VFX slash.", "Añade los efectos del corte.")] == ["VFX", "Slash"]
    with pytest.raises(ValueError):
        style.parse({"register": "vos"})


def _fake_ollama(calls, fail_on=None):
    """Ollama's HTTP API: /api/chat answers each block; /api/generate with keep_alive 0 unloads."""
    def fake(settings, path, body, timeout):
        calls.append((path, body))
        if path == "/api/generate":
            return {"done": True}
        segs = json.loads(body["messages"][1]["content"])["segments"]
        if fail_on and segs[0]["id"] >= fail_on:
            raise RuntimeError("Ollama answered 500: out of memory")
        return {"message": {"content": json.dumps({"segments": [{"id": s["id"], "text": f"Local {s['id']}."} for s in segs]})}}
    return fake


def test_ollama_translates_with_the_same_prompt_and_schema_then_unloads(wd, monkeypatch):
    calls = []
    monkeypatch.setattr(translate, "_ollama", _fake_ollama(calls))
    monkeypatch.setattr(translate, "_call_cli", lambda *a: pytest.fail("Claude was asked"))
    monkeypatch.setattr(translate, "check_claude_reachable", lambda: pytest.fail("Claude was checked"))
    settings = Settings(backend="ollama", ollama_model="qwen3:30b-a3b", batch_size=4, chars_per_second=15)
    result = translate.run(wd, settings)
    assert [s.text for s in result] == [f"Local {i}." for i in range(1, 8)]
    chats = [b for p, b in calls if p == "/api/chat"]
    assert len(chats) == 2 and chats[0]["model"] == "qwen3:30b-a3b" and chats[0]["format"] == translate.SCHEMA
    assert chats[0]["messages"][0]["content"].startswith("You are a professional dubbing translator")
    assert calls[-1] == ("/api/generate", {"model": "qwen3:30b-a3b", "keep_alive": 0})  # GPU freed for the voice
    assert settings.translator() == "ollama:qwen3:30b-a3b"


def test_ollama_is_unloaded_even_when_a_block_fails(wd, monkeypatch):
    calls = []
    monkeypatch.setattr(translate, "_ollama", _fake_ollama(calls, fail_on=5))
    with pytest.raises(SystemExit, match="Ollama did not return"):
        translate.run(wd, Settings(backend="ollama", ollama_model="m", batch_size=4, chars_per_second=15))
    assert calls[-1][0] == "/api/generate"


def test_ollama_shortens_and_unloads_beside_the_voice_model(monkeypatch):
    calls = []

    def fake(settings, path, body, timeout):
        calls.append(path)
        return {"done": True} if path == "/api/generate" else {"message": {"content": json.dumps(
            {"segments": [{"id": 3, "text": "Corta."}]})}}

    monkeypatch.setattr(translate, "_ollama", fake)
    items = [(3, "Original long text.", "Traducción demasiado larga.", 12)]
    assert translate.shorten(items, "es-ES-AlvaroNeural", Settings(backend="ollama")) == {3: "Corta."}
    assert calls == ["/api/chat", "/api/generate"]


def test_claude_keeps_its_cache_key_and_never_calls_ollama(wd, monkeypatch):
    monkeypatch.setattr(translate, "_ollama", lambda *a: pytest.fail("Ollama was called"))
    monkeypatch.setattr(translate, "_call_cli", lambda system, prompt, model: (
        {"segments": [{"id": s["id"], "text": "x"} for s in json.loads(prompt)["segments"]]}, 0.0))
    translate.run(wd, Settings(batch_size=10, chars_per_second=15))
    assert Settings().translator() == "claude-sonnet-5-5"
