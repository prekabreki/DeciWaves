"""Parse `docs/forbidden_west_gamescript.md` into ordered dialogue records.

The gamescript is HTML-scraped prose: one `Speaker: text` line per spoken
line, `[stage directions]` in brackets, ALL-CAPS quest/section headers, and
preamble cruft at the top. This yields ordered `(index, speaker, text)` records
that serve triple duty downstream: speaker + subtitle + story position for
each ASR-matched clip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# "Aloy: ...", "Tilda van der Meer: ...", "Aloy & Morlund: ...". Speaker starts
# uppercase and holds no colon; the first ": " splits speaker from spoken text.
_SPEAKER_RE = re.compile(r"^(?P<speaker>[A-Z][^:]{0,40}): (?P<text>.+)$")
# Parenthetical stage directions inside a line, e.g. "(offscreen)", "(sighs)".
_PAREN_RE = re.compile(r"\([^)]*\)")


@dataclass(frozen=True)
class ScriptLine:
    index: int       # 0-based position in dialogue order
    speaker: str
    text: str        # spoken text, stage-direction parentheticals removed
    quest: str       # most recent quest/section header in effect ("" if none)


def _clean_text(text: str) -> str:
    return _PAREN_RE.sub(" ", text).strip()


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _is_header(stripped: str) -> bool:
    """A standalone non-speaker line that names a quest/section.

    ALL-CAPS = main quest ("THE EMBASSY"); Title-Case = sidequest ("Breaking Even",
    "Deep Trouble (start)"). Excludes prose: headers are short noun phrases with no
    sentence-ending punctuation. (Caller gates Title-Case ones on content having
    started, so top-of-file blog/metadata cruft is skipped.)
    """
    if stripped.isupper():
        return True
    core = _clean_text(stripped)                 # drop "(start)"/"(continue)" first
    return bool(core) and core[0].isupper() and len(core.split()) <= 7 \
        and core[-1] not in ".,!?;:" and "\t" not in stripped


def parse(text: str) -> list[ScriptLine]:
    lines: list[ScriptLine] = []
    quest = ""
    index = 0
    content_started = False           # gate Title-Case headers past the preamble
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("["):
            continue
        m = _SPEAKER_RE.match(stripped)
        if m:
            content_started = True
            spoken = _collapse_ws(_clean_text(m.group("text")))
            lines.append(ScriptLine(index, m.group("speaker"), spoken, quest))
            index += 1
        elif stripped.isupper():
            quest = _collapse_ws(_clean_text(stripped))
            content_started = True
        elif content_started and _is_header(stripped):
            quest = _collapse_ws(_clean_text(stripped))
    return lines


def parse_file(path: str | Path) -> list[ScriptLine]:
    return parse(Path(path).read_text(encoding="utf-8"))
