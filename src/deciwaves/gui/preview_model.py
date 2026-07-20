"""Qt-free preview resolver (#71, spec §6.5): turn a Library ``line_id`` into a playable
WAV path, decoding on demand and caching into render's own cache dirs so a later render
reuses the work (and a prior render's cache short-circuits the decode entirely).

This module holds ALL of preview's decode logic; every import here is non-Qt (the same
``engine.audio_clip`` / ``games.hzd.atrac9`` / ``engine.pack.*`` the render stages use), so
it imports and unit-tests on the base ``.[test]`` install with no PySide6. The thin
:mod:`deciwaves.gui.preview` Qt player drives it off the UI thread.

Per game (mirrors each render stage's call site):

- **FW** -- ``LineRow.audio_path`` already points at ``out/fw/<wav>`` (extract writes the WAVs
  to disk), so preview just returns it; no decode.
- **DS** -- ``LineRow.audio_path`` *is* the Decima ``.core.stream`` virtual path; decode via
  ``engine.audio_clip.clip_wav`` against a ``PackIndex`` (globs+hashes every ``.bin`` -- built
  once per resolver and cached), writing to render's ``out/wav-cache`` (``engine/render.py``).
- **HZD** -- the row carries no coords, so re-read two artifacts once per resolver:
  ``asr-manifest.csv`` (``line_id -> clip_row``) and ``clip-index.csv``
  (``clip_row -> (offset, a_bytes)``); read the ATRAC9 bytes from the voice DSAR archive and
  decode via ``games.hzd.atrac9.decode_wem_to_wav`` into ``out/hzd/wav-cache/<clip_row>.wav``
  (``games/hzd/render.py`` writes the same file).
"""
from __future__ import annotations

import csv
import os

from deciwaves.cli import config
from deciwaves.engine.audio_clip import clip_wav
from deciwaves.engine.pack.bin_index import PackIndex
from deciwaves.engine.pack.hzd_package import HzdPackage
from deciwaves.games.hzd.atrac9 import decode_wem_to_wav
from deciwaves.games.hzd.catalog import load_hzd_manifest_join
from deciwaves.games.hzd.profile import VOICE_ARCHIVE

# render's own cache paths (engine/render.py --cache default = out/wav-cache, hzd render's
# --cache default = out/hzd/wav-cache), so preview and render share one cache both ways.
_DS_CACHE = ("out", "wav-cache")
_HZD_CACHE = ("out", "hzd", "wav-cache")

# render's cache-hit guard: a real decoded WAV is always larger than a bare 44-byte header.
_MIN_WAV_BYTES = 44


class PreviewError(Exception):
    """A preview that cannot play, carrying a friendly, user-facing message (unconfigured
    install/package, unknown line, missing clip coords/file, or a decode failure)."""


def _cache_hit(wav_path: str) -> bool:
    return os.path.isfile(wav_path) and os.path.getsize(wav_path) > _MIN_WAV_BYTES


def _read_csv(path: str) -> list[dict]:
    """``csv.DictReader`` rows for *path*, or ``[]`` if absent/unreadable. ``utf-8-sig`` so a
    BOM is consumed rather than fused onto the first header (the repo's recurring BOM theme)."""
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError):
        return []


class PreviewResolver:
    """Resolves ``line_id -> playable WAV`` for one (game, workspace, config). Build a fresh
    one whenever the game or workspace changes -- heavy handles (DS ``PackIndex``, HZD
    ``HzdPackage`` + the two coord dicts) are built lazily on first use and cached for the
    resolver's lifetime, so repeated previews of the same game are fast."""

    def __init__(self, game: str, workspace: str, cfg: dict | None = None):
        self._game = game
        self._workspace = workspace
        self._cfg = cfg if cfg is not None else config.load()
        self._ds_index: PackIndex | None = None
        self._ds_index_key: tuple[str, str] | None = None
        self._hzd_pkg: HzdPackage | None = None
        self._hzd_maps: tuple[dict[str, str], dict[int, tuple[int, int]]] | None = None

    def resolve_wav(self, line_id: str, audio_path: str | None) -> str:
        """Return a playable WAV path for *line_id*, decoding+caching on a miss. *audio_path*
        is the row's ``audio_path`` (FW WAV / DS stream path; unused for HZD, whose coords come
        from the manifests). Raises :class:`PreviewError` with friendly text on any failure."""
        if self._game == "fw":
            return self._resolve_fw(audio_path)
        if self._game == "ds":
            return self._resolve_ds(audio_path)
        if self._game == "hzd":
            return self._resolve_hzd(line_id)
        raise PreviewError(f"Preview is not supported for game {self._game!r}.")

    # --- FW ----------------------------------------------------------------

    def _resolve_fw(self, audio_path: str | None) -> str:
        if not audio_path:
            raise PreviewError("This line has no extracted audio.")
        if not os.path.isfile(audio_path):
            raise PreviewError(f"Audio file not found: {audio_path}")
        return audio_path

    # --- DS ----------------------------------------------------------------

    def _resolve_ds(self, stream_path: str | None) -> str:
        if not stream_path:
            raise PreviewError("This line has no audio stream.")
        data_dir, oodle = config.resolve_ds_install(self._cfg)
        if not data_dir or not oodle:
            raise PreviewError("DS install is not configured. Run `deciwaves setup` first.")
        idx = self._ds_pack_index(data_dir, oodle)
        cache_dir = os.path.join(self._workspace, *_DS_CACHE)
        try:
            wav_path, _dur = clip_wav(idx, stream_path, cache_dir)
        except Exception as exc:  # ClipError / decode failure -> friendly, never a GUI crash
            raise PreviewError(f"Could not decode audio: {exc}") from exc
        return wav_path

    def _ds_pack_index(self, data_dir: str, oodle: str) -> PackIndex:
        key = (data_dir, oodle)
        if self._ds_index is None or self._ds_index_key != key:
            self._ds_index = PackIndex(data_dir, oodle)  # expensive: globs+hashes every .bin
            self._ds_index_key = key
        return self._ds_index

    # --- HZD ---------------------------------------------------------------

    def _resolve_hzd(self, line_id: str) -> str:
        line_to_clip, clip_coords = self._load_hzd_maps()
        clip_row = line_to_clip.get(line_id)
        if clip_row is None:
            raise PreviewError(f"No audio clip is bound to line {line_id!r} yet.")
        try:
            cr = int(clip_row)
        except (TypeError, ValueError):
            raise PreviewError(f"Line {line_id!r} has an invalid clip row {clip_row!r}.") from None
        coords = clip_coords.get(cr)
        if coords is None:
            raise PreviewError(f"No clip coordinates for line {line_id!r}.")
        wav_path = os.path.join(self._workspace, *_HZD_CACHE, f"{cr}.wav")
        if _cache_hit(wav_path):
            return wav_path
        package = self._cfg.get("hzd_package")
        if not package:
            raise PreviewError("HZD package is not configured. Run `deciwaves setup` first.")
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)
        dsar = self._hzd_dsar(package)
        try:
            wem = dsar.read(*coords)
            decode_wem_to_wav(wem, wav_path)
        except Exception as exc:  # bad read / decode failure -> friendly, never a GUI crash
            raise PreviewError(f"Could not decode audio for line {line_id!r}: {exc}") from exc
        return wav_path

    def _hzd_dsar(self, package: str):
        if self._hzd_pkg is None:
            self._hzd_pkg = HzdPackage(package)
        return self._hzd_pkg.dsar_for(VOICE_ARCHIVE)

    def _load_hzd_maps(self) -> tuple[dict[str, str], dict[int, tuple[int, int]]]:
        """``(line_id -> clip_row, clip_row -> (offset, a_bytes))`` from the HZD
        manifests, loaded once and cached. Delegates to the shared
        ``catalog.load_hzd_manifest_join`` instead of re-implementing the join."""
        if self._hzd_maps is None:
            root = os.path.join(self._workspace, "out", "hzd")
            self._hzd_maps = load_hzd_manifest_join(
                os.path.join(root, "asr-manifest.csv"),
                os.path.join(root, "clip-index.csv"),
            )
        return self._hzd_maps
