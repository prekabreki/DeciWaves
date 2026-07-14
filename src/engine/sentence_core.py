"""Parse one DS:DC dialogue .core (in memory) into voice-line rows."""
from __future__ import annotations
import io
import os
from dataclasses import dataclass

import pydecima.reader as reader
from pydecima.resources.SentenceGroupResource import SentenceGroupResource
from pydecima.resources.LocalizedTextResource import LocalizedTextResource
from pydecima.resources.LocalizedSimpleSoundResource import LocalizedSimpleSoundResource


@dataclass
class Line:
    line_id: str
    line_index: int
    speaker_code: str
    subtitle_en: str
    wem_path_en: str


def _wem_stem(wem_path_en: str) -> str:
    # ".../sentences_sentence_<uuid>.wem.english" -> "sentences_sentence_<uuid>"
    base = os.path.basename(wem_path_en)
    return base.split(".wem.")[0] if ".wem." in base else ""


def parse_sentences(core_bytes: bytes, on_line_error=None) -> list[Line]:
    objs: dict = {}
    reader.read_objects_from_stream(io.BytesIO(core_bytes), objs)
    groups = [o for o in objs.values() if isinstance(o, SentenceGroupResource)]
    groups.sort(key=lambda g: g.name or "")

    lines: list[Line] = []
    index = 0
    for g in groups:
        for sref in g.sentences:
            i = index
            index += 1
            try:
                sent = sref.follow(objs)
                if sent is None:
                    if on_line_error:
                        on_line_error(i, ValueError("sentence ref did not resolve"))
                    continue
                speaker_code = getattr(sent.voice, "path", "") or ""
                subtitle = ""
                if sent.text.type != 0:
                    t = sent.text.follow(objs)
                    if isinstance(t, LocalizedTextResource):
                        subtitle = t.language[0] if t.language else ""
                wem = ""
                if sent.sound.type != 0:
                    s = sent.sound.follow(objs)
                    if isinstance(s, LocalizedSimpleSoundResource):
                        wem = s.wem_paths[0] if s.wem_paths else ""
                line_id = _wem_stem(wem) or f"{g.name or 'group'}#{i}"
                lines.append(Line(line_id, i, speaker_code, subtitle, wem))
            except Exception as exc:  # fail-soft per line
                if on_line_error:
                    on_line_error(i, exc)
                continue
    return lines
