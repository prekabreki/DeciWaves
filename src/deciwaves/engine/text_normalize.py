"""Transcript/subtitle text normalization shared across games' ASR-content-matching.

Strips markup and punctuation so an ASR transcript and a game subtitle can be compared
on words alone. Game-agnostic: used by HZD's ASR bucket matcher (`games/hzd/match.py`,
subtitle directives like ``<subtitle-delay=..>``/``<split..>``) and FW's subtitle/script
matching (`games/fw/subtitle_match.py`, `games/fw/subtitle_bind.py`, `games/fw/dlc.py`,
timing tokens like ``<time0.17>``) — both games wrap non-spoken directives in the same
``<...>`` markup convention.
"""
from __future__ import annotations
import re

_MARKUP = re.compile(r"<[^>]*>")        # subtitle directives, e.g. <subtitle-delay=..>, <time0.17>
_PUNCT = re.compile(r"[^\w\s]")


def normalize(s):
    s = _MARKUP.sub(" ", s)             # drop markup before punctuation (not spoken)
    return re.sub(r"\s+", " ", _PUNCT.sub("", s.lower())).strip()
