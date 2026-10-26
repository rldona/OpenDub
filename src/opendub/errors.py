"""Phase failures the web shows in the page's language.

A phase stops with SystemExit and an English message, which the CLI prints. The common
failures raise PhaseError instead, still a SystemExit with the same message, plus a code
and its parameters: a web job keeps them (web/jobs.py) and the page says it in Spanish
or English (frontend err_phase_<code>), the English text as the detail.
"""

from __future__ import annotations

from typing import Any

# The codes, each with the parameters its message takes (the frontend's i18n keys match)
CODES = {
    "youtube_blocked": (),  # YouTube's bot check refused the download
    "youtube_unreachable": (),  # no connection to YouTube
    "claude_unreachable": ("host",),
    "ollama_unreachable": ("host",),
    "engine_missing": ("engine", "cmd"),  # a voice engine or the separator isn't installed
    "diarizer_missing": ("cmd",),
    "clips_deleted": (),  # deleted to save space: a retouch needs them
}


class PhaseError(SystemExit):
    def __init__(self, code: str, message: str, **params: Any):
        if code not in CODES or set(params) != set(CODES[code]):
            raise ValueError(f"PhaseError {code!r} with {sorted(params)}")
        super().__init__(message)  # SystemExit.code: the message the CLI prints
        self.error_code = code
        self.params = params
