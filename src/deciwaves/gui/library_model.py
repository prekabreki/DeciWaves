"""Qt-free Library-view model (#70, spec §6): parse the per-game list artifact into a
normalized ``LineRow`` list, and provide the pure filter/sort/selection logic the thin
widget renders. Imports without PySide6 and unit-tests on the base ``.[test]`` install.

Deliberately import-light: reads artifacts with ``csv.DictReader`` and never imports
``deciwaves.games.*`` (those pull pydecima / heavy parsers). The columns each game writes
are verified against the stage code:

- **DS** artifacts live in ``out/`` ROOT (spec §9 gotcha #6): story ``out/playlist.csv``
  (``games/ds/story_order.py`` ``PLAYLIST_COLUMNS``) else ``out/catalog.csv``
  (``engine/catalog_io.py`` ``CSV_COLUMNS``). No length source in either -> ``length_s`` None.
- **HZD** under ``out/hzd/``: story ``asr-manifest.csv`` (``games/hzd/asr_bind.py``
  ``MANIFEST_COLS``) else ``catalog.csv`` (same 10-col DS schema, ``wem_path_en`` empty).
  Length: the manifest carries no duration, but ``clip-index.csv``
  (``games/hzd/clip_index.py``) carries ``b_samples`` (the ATRAC9 fact sample-count) keyed
  by ``clip_row``; joined and divided by the 48 kHz voice rate for a proxy duration (exact
  only at decode, spec §6.2). Pre-bind (catalog only) there is no ``clip_row`` to join ->
  ``length_s`` None.
- **FW** under ``out/fw/``: story ``full-reel-manifest.csv`` else ``subtitle-manifest-full.csv``
  (both ``games/fw/manifest.py`` ``MANIFEST_COLS`` -- the latter is what a user with
  ``types.json`` but no BYO gamescript gets from ``subtitle-bind``, carrying subtitles +
  speaker) else ``clip-index.csv`` (``games/fw/extract.py`` ``MANIFEST_COLS``, ids + wav only).
  Every source carries a ``wav`` path relative to ``out/fw/``; length is probed from that
  WAV's header when the file exists (post-extract).
"""
from __future__ import annotations

import csv
import json
import os
import struct
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from deciwaves.engine.atomic_io import atomic_write

# HZD story voice is 48 kHz mono ATRAC9 (games/hzd/sentence_fw.py comment); b_samples is the
# decoded fact sample-count, so b_samples / 48000 is a duration proxy (exact value comes at
# decode, when render reads the real WAV frame rate).
_HZD_SAMPLE_RATE = 48000

_NONE_SUBTITLE = "(none)"


@dataclass(frozen=True)
class LineRow:
    """One voice line, normalized across games. ``None`` marks a field the current
    artifact/stage cannot supply yet (spec §6.2). ``order_index`` is the row's position in
    the source file -- the default sort key, which yields story order when the story-order
    artifact was loaded and artifact order otherwise."""
    line_id: str
    name: str | None = None
    length_s: float | None = None
    speaker: str | None = None
    subtitle: str | None = None
    scene: str | None = None
    category: str | None = None
    tier: str | None = None
    audio_path: str | None = None
    is_dupe: bool = False
    has_subtitle: bool = False
    order_index: int = 0
    search_haystack: str = ""


# --- artifact reading ------------------------------------------------------

def _read_csv(path: str) -> list[dict]:
    """``csv.DictReader`` rows for *path*, or ``[]`` if the file is absent/unreadable.

    Opened as ``utf-8-sig`` so a UTF-8 BOM is consumed rather than fused onto the first
    header (``\\ufeffline_id``), which would silently parse every ``line_id`` as ``""``
    and key the whole selection under one blank id (the repo's recurring BOM-mojibake
    theme -- issues #59/#84). ``utf-8-sig`` reads both BOM and no-BOM files."""
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError):
        return []


def _has_subtitle(subtitle: str | None) -> bool:
    """True when *subtitle* is real text -- not empty/whitespace and not the ``(none)``
    sentinel the pipeline uses for a line with no subtitle."""
    if not subtitle:
        return False
    s = subtitle.strip()
    return bool(s) and s.lower() != _NONE_SUBTITLE


def _out_dir(workspace: str, game: str) -> str:
    """Artifact root for *game*: ``out/`` for DS, ``out/<game>/`` for HZD/FW (spec §9 #6)."""
    return os.path.join(workspace, "out") if game == "ds" else os.path.join(workspace, "out", game)


def _precompute_haystack(r: LineRow) -> LineRow:
    hay = " ".join(x for x in (r.subtitle, r.line_id, r.name) if x).lower()
    return replace(r, search_haystack=hay)


def load_lines(workspace: str, game: str) -> list[LineRow]:
    """Load the game's list artifact (story-order if present, else catalog) into
    normalized ``LineRow``s, with dupe/has-subtitle marking applied. Missing artifact -> []."""
    if game == "ds":
        rows = _load_ds(workspace)
    elif game == "hzd":
        rows = _load_hzd(workspace)
    elif game == "fw":
        rows = _load_fw(workspace)
    else:
        rows = []
    rows = _mark_dupes(rows)
    return [_precompute_haystack(r) for r in rows]


def _load_ds(workspace: str) -> list[LineRow]:
    root = _out_dir(workspace, "ds")
    playlist = os.path.join(root, "playlist.csv")
    if os.path.isfile(playlist):
        out = []
        for i, r in enumerate(_read_csv(playlist)):
            sub = r.get("subtitle")
            out.append(LineRow(
                line_id=r.get("line_id", ""), speaker=r.get("speaker") or None,
                subtitle=sub, scene=r.get("scene") or None, category=r.get("category") or None,
                audio_path=r.get("stream_path") or None, has_subtitle=_has_subtitle(sub),
                order_index=i))
        return out
    return _load_ds_catalog_shape(os.path.join(root, "catalog.csv"))


def _load_ds_catalog_shape(path: str) -> list[LineRow]:
    """The 10-column catalog schema shared by DS and HZD (engine/catalog_io CSV_COLUMNS)."""
    out = []
    for i, r in enumerate(_read_csv(path)):
        sub = r.get("subtitle_en")
        out.append(LineRow(
            line_id=r.get("line_id", ""), speaker=r.get("speaker_name") or None,
            subtitle=sub, scene=r.get("scene") or None, category=r.get("category") or None,
            audio_path=r.get("wem_path_en") or None, has_subtitle=_has_subtitle(sub),
            order_index=i))
    return out


def _load_hzd(workspace: str) -> list[LineRow]:
    root = _out_dir(workspace, "hzd")
    manifest = os.path.join(root, "asr-manifest.csv")
    if os.path.isfile(manifest):
        b_samples = _hzd_b_samples_by_clip_row(os.path.join(root, "clip-index.csv"))
        out = []
        for i, r in enumerate(_read_csv(manifest)):
            sub = r.get("subtitle_en")
            samples = b_samples.get(r.get("clip_row", ""))
            out.append(LineRow(
                line_id=r.get("line_id", ""), speaker=r.get("speaker_name") or None,
                subtitle=sub, scene=r.get("scene") or None, tier=r.get("tier") or None,
                length_s=(samples / _HZD_SAMPLE_RATE if samples else None),
                has_subtitle=_has_subtitle(sub), order_index=i))
        return out
    return _load_ds_catalog_shape(os.path.join(root, "catalog.csv"))


def _hzd_b_samples_by_clip_row(clip_index_path: str) -> dict[str, int]:
    """``clip_row -> b_samples`` from the HZD clip-index, skipping 0/blank sample counts
    (a clip whose ATRAC9 fact-count didn't parse is written as 0 -- no honest duration)."""
    out: dict[str, int] = {}
    for r in _read_csv(clip_index_path):
        try:
            n = int(r.get("b_samples", "") or 0)
        except ValueError:
            n = 0
        if n > 0:
            out[r.get("clip_row", "")] = n
    return out


def _load_fw(workspace: str) -> list[LineRow]:
    root = _out_dir(workspace, "fw")
    # Both manifests share fw/manifest.py MANIFEST_COLS, so one parse path serves both.
    # full-reel wins (gamescript-anchored story order); else subtitle-manifest-full, which a
    # user with types.json but no BYO gamescript still gets from subtitle-bind and which
    # carries subtitles + speaker (spec §6.1). Only if neither exists do we fall back to the
    # subtitle-less clip-index.
    for name in ("full-reel-manifest.csv", "subtitle-manifest-full.csv"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return _load_fw_manifest(root, path)
    # clip-index: ids + wav paths only, no subtitle/speaker yet (pre subtitle-bind).
    out = []
    for i, r in enumerate(_read_csv(os.path.join(root, "clip-index.csv"))):
        audio = _fw_audio_path(root, r.get("wav"))
        out.append(LineRow(
            line_id=r.get("line_id", ""), audio_path=audio,
            length_s=None, has_subtitle=False, order_index=i))
    return out


def _load_fw_manifest(root: str, path: str) -> list[LineRow]:
    """Parse a FW labeled manifest (``full-reel-manifest.csv`` or
    ``subtitle-manifest-full.csv`` -- identical ``fw/manifest.py MANIFEST_COLS`` schema)."""
    out = []
    for i, r in enumerate(_read_csv(path)):
        sub = r.get("subtitle")
        audio = _fw_audio_path(root, r.get("wav"))
        out.append(LineRow(
            line_id=r.get("line_id", ""), speaker=r.get("speaker") or None,
            subtitle=sub, scene=r.get("quest") or None, tier=r.get("tier") or None,
            audio_path=audio, length_s=None,
            has_subtitle=_has_subtitle(sub), order_index=i))
    return out


def _fw_audio_path(fw_root: str, wav_rel: str | None) -> str | None:
    """Resolve a FW manifest ``wav`` (relative to ``out/fw/``) to an absolute path."""
    if not wav_rel:
        return None
    return os.path.normpath(os.path.join(fw_root, wav_rel))


def _mark_dupes(rows: list[LineRow]) -> list[LineRow]:
    """Mark within-scene exact-subtitle repeats (2nd+ occurrence) as dupes, mirroring DS
    render's within-scene exact-dupe pruning. Empty/no-subtitle rows never count as dupes."""
    seen: set[tuple[str | None, str]] = set()
    out = []
    for r in rows:
        dupe = False
        if r.has_subtitle:
            key = (r.scene, (r.subtitle or "").strip())
            dupe = key in seen
            seen.add(key)
        out.append(replace(r, is_dupe=dupe) if dupe != r.is_dupe else r)
    return out


# --- WAV-header duration reader (no external deps) -------------------------

# Cache keyed by (normalized_path, mtime): a WAV file at the same path with the same
# modification time must have the same header -> reusing it avoids tens of thousands of
# opens across repeated refreshes. None values are also cached (absent / unparseable files).
_DURATION_CACHE: dict[tuple[str, float], float | None] = {}
_DURATION_CACHE_LOCK = threading.Lock()


def _cached_wav_duration(path: str | None) -> float | None:
    """Duration from the cache or by opening the WAV header. Keyed on (path, mtime) so
    re-probes happen only when the file is actually different. If the file is absent we
    return the last-cached value for that path — the next fresh probe with a new mtime
    will naturally evict it."""
    if not path:
        return None
    resolved = str(Path(path).resolve())
    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        current_mtime = 0.0

    with _DURATION_CACHE_LOCK:
        key = (resolved, current_mtime)
        if key in _DURATION_CACHE:
            return _DURATION_CACHE[key]
        if current_mtime == 0.0:
            for (p, _), dur in _DURATION_CACHE.items():
                if p == resolved:
                    return dur
        if current_mtime == 0.0 or not os.path.isfile(path):
            return None
        _DURATION_CACHE[key] = wav_duration_seconds(path)
        return _DURATION_CACHE[key]


def resolve_wav_durations(rows: list[LineRow]) -> dict[str, float | None]:
    """Probe WAV headers for every row that carries an ``audio_path``, using and populating
    the path+mtime cache. Returns ``{line_id: duration_seconds}``, including ``None`` for
    rows whose WAV couldn't be probed (absent / unparseable).

    This function does real file I/O and is expected to run on a background thread; the
    calling view feeds its results back into the model via ``dataChanged`` for the length
    column only."""
    return {r.line_id: _cached_wav_duration(r.audio_path) for r in rows}


def wav_duration_seconds(path: str | None) -> float | None:
    """Duration in seconds from a WAV file's header, or ``None`` if the file is
    absent/unreadable or not a parseable PCM WAV.

    Walks RIFF chunks for ``fmt `` (sample rate, channels, bits-per-sample) and ``data``
    (payload size); duration = data_bytes / (sample_rate * channels * bits/8). Reads only the
    header region, tolerates unexpected bytes by returning ``None``."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            sample_rate = channels = bits = data_bytes = 0
            while True:
                chunk = f.read(8)
                if len(chunk) < 8:
                    break
                cid, size = chunk[:4], struct.unpack("<I", chunk[4:8])[0]
                if cid == b"fmt ":
                    fmt = f.read(size)
                    if len(fmt) < 16:
                        return None
                    channels = struct.unpack("<H", fmt[2:4])[0]
                    sample_rate = struct.unpack("<I", fmt[4:8])[0]
                    bits = struct.unpack("<H", fmt[14:16])[0]
                elif cid == b"data":
                    data_bytes = size
                    break
                else:
                    f.seek(size + (size & 1), os.SEEK_CUR)  # chunks are word-aligned
        bytes_per_sec = sample_rate * channels * (bits // 8)
        if bytes_per_sec <= 0 or data_bytes <= 0:
            return None
        return data_bytes / bytes_per_sec
    except (OSError, ValueError, struct.error):
        return None


# --- filters / sort (view-only; never mutate selection) --------------------

def visible_rows(rows: list[LineRow], *, search: str, speaker: str,
                 hide_dupes: bool, hide_no_subtitle: bool) -> list[LineRow]:
    """The rows the table should show under the current filters. Pure -- selection is
    untouched. ``speaker`` == ``"all"`` (or empty) means no speaker filter."""
    needle = (search or "").strip().lower()
    want_speaker = speaker not in (None, "", "all")
    out = []
    for r in rows:
        if hide_dupes and r.is_dupe:
            continue
        if hide_no_subtitle and not r.has_subtitle:
            continue
        if want_speaker and r.speaker != speaker:
            continue
        if needle:
            hay = r.search_haystack if r.search_haystack else " ".join(
                x for x in (r.subtitle, r.line_id, r.name) if x).lower()
            if needle not in hay:
                continue
        out.append(r)
    return out


def distinct_speakers(rows: list[LineRow]) -> list[str]:
    """Sorted distinct non-empty speaker names, for the filter dropdown."""
    return sorted({r.speaker for r in rows if r.speaker})


def _value_key(key: str | None):
    """A function returning the comparable value for *key* on a row, or ``None`` when the
    row has no value for that column. Returns ``None`` (the function) for order-based keys."""
    if key in ("line_id", "id", "name"):
        return lambda r: ((r.name or r.line_id) or "").lower() or None
    if key in ("length", "length_s"):
        return lambda r: r.length_s
    if key == "speaker":
        return lambda r: (r.speaker or "").lower() or None
    if key == "subtitle":
        return lambda r: (r.subtitle or "").lower() or None
    if key in ("scene", "category", "tier"):
        return lambda r, k=key: (getattr(r, k) or "").lower() or None
    return None


def sort_rows(rows: list[LineRow], key: str | None, descending: bool = False) -> list[LineRow]:
    """Stable sort by *key* (a ``LineRow`` column; ``None``/``order_index`` -> file/story
    order). Rows with no value for the column always sort last, in both directions, so
    unknown lengths/speakers never jump to the top of a descending sort."""
    vk = _value_key(key)
    if vk is None:
        return sorted(rows, key=lambda r: r.order_index, reverse=descending)
    known = sorted((r for r in rows if vk(r) is not None), key=vk, reverse=descending)
    unknown = [r for r in rows if vk(r) is None]
    return known + unknown


def has_known_lengths(rows: list[LineRow]) -> bool:
    """True when at least one row has a known length -- gates the duration/short controls."""
    return any(r.length_s is not None for r in rows)


# --- selection persistence + commands (spec §6.4) --------------------------

def selection_path(workspace: str, game: str) -> str:
    """``out/<game>/gui/selection.json`` for ALL games (the GUI owns this namespace even
    for DS, whose pipeline artifacts sit in ``out/`` root)."""
    return os.path.join(workspace, "out", game, "gui", "selection.json")


def load_selection(workspace: str, game: str) -> set[str]:
    """The set of *unchecked* line_ids (checked is the default). Missing/corrupt -> empty
    set (everything checked)."""
    try:
        with open(selection_path(workspace, game), "r", encoding="utf-8") as f:
            obj = json.load(f)
        unchecked = obj.get("unchecked", [])
        return {str(x) for x in unchecked}
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def save_selection(workspace: str, game: str, unchecked: set[str]) -> None:
    """Persist the unchecked set atomically to ``out/<game>/gui/selection.json``."""
    path = selection_path(workspace, game)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"unchecked": sorted(unchecked)}

    def _write(tmp_path):
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=0)

    atomic_write(path, _write)


def uncheck_shorter_than(rows: list[LineRow], unchecked: set[str], seconds: float) -> set[str]:
    """Uncheck every row with a *known* length below *seconds*; rows of unknown length are
    left alone. Returns the new unchecked set (union with the current one)."""
    add = {r.line_id for r in rows if r.length_s is not None and r.length_s < seconds}
    return set(unchecked) | add


def _word_count(subtitle: str | None) -> int:
    return len((subtitle or "").split())


def uncheck_barks(rows: list[LineRow], unchecked: set[str], game: str) -> set[str]:
    """Uncheck bark/chatter lines using the pipeline's own per-game heuristics (spec §6.4).
    ``tier`` is match-confidence, NOT a bark flag, so it is deliberately not consulted here.

    - HZD: ``category == "ambient"`` or no subtitle (render skips both).
    - FW: no subtitle (barks never bind) or a subtitle below a small word-count floor.
    - DS: empty-subtitle rows (mostly already gone by story-order time)."""
    def is_bark(r: LineRow) -> bool:
        if game == "hzd":
            return r.category == "ambient" or not r.has_subtitle
        if game == "fw":
            return not r.has_subtitle or _word_count(r.subtitle) < 2
        return not r.has_subtitle  # ds
    return set(unchecked) | {r.line_id for r in rows if is_bark(r)}


def check_all(rows: list[LineRow]) -> set[str]:
    """Check everything -> the unchecked set is empty."""
    return set()


def check_none(rows: list[LineRow]) -> set[str]:
    """Uncheck everything -> the unchecked set is every line_id."""
    return {r.line_id for r in rows}


# --- preview availability (▷ column state; playback itself is #71) ----------

def is_bind_done(workspace: str, game: str) -> bool:
    """Whether the game's ``bind`` stage has completed (``out/<game>/.done-bind``)."""
    return os.path.isfile(os.path.join(workspace, "out", game, ".done-bind"))


def preview_available(row: LineRow, game: str, *, bind_done: bool) -> bool:
    """Whether the ▷ preview is playable now (spec §6.5), computed **without a per-row
    filesystem syscall** so it is safe to call on the paint path across tens of thousands of
    rows: DS always (on-demand decode); HZD only once ``bind`` has produced clips (a single
    per-refresh bool); FW iff the row carries a WAV path -- extract writes the WAVs to disk
    right after extract (spec §6.2), so a non-empty ``audio_path`` means playable, no ``stat``."""
    if game == "fw":
        return bool(row.audio_path)
    if game == "ds":
        return True
    if game == "hzd":
        return bind_done
    return False


def availability_by_id(rows: list[LineRow], game: str, *, bind_done: bool) -> dict[str, bool]:
    """``line_id -> preview-available`` lookup, computed once per refresh (O(n), no per-row
    syscall) so the table model can read ▷ availability O(1) on paint (spec §6.2/§6.5)."""
    return {r.line_id: preview_available(r, game, bind_done=bind_done) for r in rows}


def preview_unavailable_tooltip(game: str, *, bind_done: bool) -> str:
    """Tooltip for an unavailable ▷ (spec §6.5): HZD pre-bind is 'available after bind'; FW
    without a WAV has no audio; anything else is a generic pending message."""
    if game == "hzd" and not bind_done:
        return "Preview available after bind"
    if game == "fw":
        return "No audio for this line"
    return "Preview unavailable"
