"""Plausibly-English text heuristic shared by ``speakers.py`` and
``sentence_core.py``.

Both DS parsing paths pull ``t.language[0]`` on the (correct) assumption
that index 0 is the English slot of a ``LocalizedTextResource``. That
assumption holds for the *layout* pydecima builds, but the vendored scanner
(``_vendor/pydecima/resources/LocalizedTextResource.py``) skips EMPTY
language slots when it scans the resource body and only pads at the end of
the list. When a resource's English slot is empty, index 0 silently lands
on the first non-empty language instead -- typically Japanese, since it is
scanned early. The vendored parser is correct by its own contract (only
``language[0] == English`` is guaranteed when the assumption above holds);
first-party callers must not blindly trust it when it doesn't.

``is_plausibly_english`` is a last line of defense against surfacing
wrong-language text: it does not know or care *why* index 0 might be wrong,
it just refuses text that is obviously not Latin-script English.
"""
from __future__ import annotations

import unicodedata

#: Exclusive upper bound (code point) for "plausibly English/Latin" text.
#: Covers Basic Latin (U+0000-007F), Latin-1 Supplement (U+0080-00FF), and
#: Latin Extended-A/B (U+0100-024F) -- so accented European names ("Muller",
#: "Walesa") pass -- while rejecting everything from U+0250 up: Greek,
#: Cyrillic, CJK ideographs, Hiragana/Katakana, Hangul, and so on.
_LATIN_MAX_CODEPOINT = 0x0250


def is_plausibly_english(text: str) -> bool:
    """Return ``True`` if *text* plausibly looks like English/Latin-script text.

    Strips whitespace and Unicode punctuation, then requires every
    remaining character's code point to be below ``U+0250``. An empty
    string, or a string that is nothing but whitespace/punctuation once
    stripped, is rejected -- there is no text to accept.
    """
    if not text:
        return False
    core = "".join(
        ch for ch in text
        if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )
    if not core:
        return False
    return all(ord(ch) < _LATIN_MAX_CODEPOINT for ch in core)
