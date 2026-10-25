# Architecture

How the pieces fit together to dub a video. Each box links to the module that
implements it under `src/opendub/`.

## Pipeline

```mermaid
flowchart TD
    cli["CLI<br/>opendub dub"] --> dub
    web["Web<br/>React dashboard on FastAPI + SSE, one job at a time"] --> dub
    dub["pipeline.dub()"] --> download

    subgraph work["work/&lt;video id&gt;/ · manifest.json caches each phase"]
        download["Download · yt-dlp + ffmpeg<br/>video, audio, thumbnail"]
        transcribe["Transcription · YouTube subtitles or faster-whisper<br/>English sentences with timings"]
        separate["Separation · HTDemucs<br/>voice apart from music and noise"]
        translate["Translation · Claude Sonnet 5.5 (claude CLI)<br/>Spanish that fits each sentence's slot"]
        tts["Voice · TTS engine<br/>Chatterbox, IndexTTS, CosyVoice or edge-tts"]
        mix["Mix · numpy + ffmpeg<br/>Spanish voice over the original background"]
        download --> transcribe --> separate --> translate --> tts --> mix
    end

    mix --> out["output.mp4 + outputs/&lt;engine&gt;.mp4"]

    classDef gpu fill:#E1F5EE,stroke:#0F6E56,color:#085041
    classDef external fill:#FAECE7,stroke:#993C1D,color:#712B13
    class transcribe,separate,tts gpu
    class download,translate external
```

Green runs on the local GPU; orange talks to an external service (YouTube,
Claude).

| Piece | Module | Role |
|---|---|---|
| CLI | `cli.py` | `dub`, `web`, `setup-indextts` commands and their flags. |
| Web | `web/app.py`, `web/jobs.py`, `web/videos.py`, `frontend/` | Job queue (one at a time), replayable SSE progress, versions with their own numbers and issues, translation editor, Ctrl+C guard. The page is a React 19 + TypeScript app (`frontend/`) built into `web/static/`. |
| Pipeline | `pipeline.py` | Runs the phases in order; `release_models()` frees GPU memory after each web job. |
| Child processes | `media.py`, `engines.py` | The single place ffmpeg, yt-dlp's children, the engine workers (IndexTTS, CosyVoice) and the `claude` CLI are started from, so the web server can keep them out of a stray Ctrl+C and stop them on exit. `engines.py` is the shared JSON-lines client of the engines that run in their own venv. |
| Download | `download.py` | yt-dlp for the video, audio and thumbnail. |
| Transcription | `transcribe.py`, `segments.py` | Uses YouTube's subtitles when available, faster-whisper otherwise; regroups pieces into sentences with timings. |
| Separation | `separate.py` | HTDemucs splits the original voice from the background, which is kept for the mix. |
| Translation | `translate.py` | Claude translates each sentence within a character budget set by the voice's pace model; keeps hand edits made in the web. |
| Voice | `tts.py`, `clone.py`, `indextts.py`, `cosyvoice.py`, `reference.py`, `spoken.py` | See below. |
| Mix | `mix.py` | Places each clip at its timestamp over the background, writes `output.mp4` and archives a copy per engine in `outputs/`. |

Every phase stores its result in `work/<video id>/` under a hash of its
parameters in `manifest.json`: changing a setting reruns only from the phase it
affects (editing the translation in the web reruns from the voice).

## Voice phase

The slowest phase (about 86% of a dub's time).

```mermaid
flowchart TD
    ref["Reference voice<br/>10–15 s of the original, fewest pauses"] --> auto
    auto{"Automatic engine<br/>mean F0 vs 165 Hz"}
    auto -- "higher" --> cb["Chatterbox Multilingual V3<br/>in-process"]
    auto -- "lower" --> itts["IndexTTS-2.5<br/>JSON-lines worker in its own Python 3.11 venv"]
    ref -. "--engine cosyvoice" .-> cv["CosyVoice 3<br/>JSON-lines worker in its own Python 3.11 venv"]
    cb --> fit
    itts --> fit
    cv --> fit
    fit["Fit to slot<br/>speed factor → Claude shortening → below floor → atempo"] --> qc
    qc["Quality check · whisper<br/>on failure: another seed → shorter sentence → fixed reference → edge-tts"] --> clips
    clips["Clips in tts/ + tts.json → mix"]
```

- **Reference** (`reference.py`): the cleanest 10–15 s stretch of the separated
  voice; its mean F0 picks the engine under `--engine auto`.
- **Pace model** (`tts.py`): seconds = overhead + characters / characters per
  second, calibrated per voice and cached. It sets the translation's character
  budget and predicts each clip's speed factor.
- **Fit to slot**: IndexTTS and CosyVoice take a speed factor between 0.7 and 1.0 (one
  measured correction); if the clip still overflows, Claude shortens the
  sentence; then the factor may go down to 0.5 (logged in `overflow.log`), and
  `atempo` covers what is left.
- **Quality check** (`clone.py`): whisper transcribes each clip, with figures
  spelled out in words (`spoken.py`), and compares it with the text; failing
  clips walk the fallback chain, ending with edge-tts (Microsoft's online
  voice).
