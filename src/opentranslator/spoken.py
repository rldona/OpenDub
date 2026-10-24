"""Numbers and symbols written out as Spanish words, the way they are spoken.

Cloned voices misread figures (IndexTTS said "192" digit by digit and "2x2" as
"2x etsos"), and whisper writes back what it hears as figures, so the quality
check compared "cinco" with "5" and flagged clips that were fine. Writing them
out before synthesis, and normalizing both sides of the check the same way,
fixes both.
"""

from __future__ import annotations

import re

from num2words import num2words

_TIMES = re.compile(r"(?<=\d)\s*[x×]\s*(?=\d)")  # 2x2, 4 x 4 → "por"
_PERCENT = re.compile(r"(\d)\s*%")
_ORDINAL = re.compile(r"\b(\d+)\s*([ºª])")
# 1.000 or 12.500.000 (Spanish thousands), 3,5 (Spanish decimals), 3.5 (English decimals left by Claude)
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?![\d.,]\d)|\d+[.,]\d+|\d+")


def _decimal(integer: str, fraction: str) -> str:
    # "0,05" → "cero coma cero cinco": leading zeros of the fraction are spoken
    zeros = len(fraction) - len(fraction.lstrip("0"))
    rest = fraction.lstrip("0")
    words = ["cero"] * zeros + ([num2words(int(rest), lang="es")] if rest else [])
    return f"{num2words(int(integer), lang='es')} coma {' '.join(words)}"


def _number(m: re.Match[str]) -> str:
    token = m.group(0)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        return num2words(int(token.replace(".", "")), lang="es")
    if sep := re.search(r"[.,]", token):
        return _decimal(token[: sep.start()], token[sep.end() :])
    return num2words(int(token), lang="es")


def _ordinal(m: re.Match[str]) -> str:
    word = num2words(int(m.group(1)), lang="es", to="ordinal")
    return word[:-1] + "a" if m.group(2) == "ª" and word.endswith("o") else word


def spell_numbers(text: str) -> str:
    """Write figures, percentages, ordinals and "NxM" out in Spanish words."""
    if not re.search(r"\d", text):
        return text
    text = _TIMES.sub(" por ", text)
    text = _PERCENT.sub(r"\1 por ciento", text)
    text = _ORDINAL.sub(_ordinal, text)
    return _NUMBER.sub(_number, text)
