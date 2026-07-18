"""Qt-free export model (#72, spec §8): the pure building blocks for the three Export-panel
flows -- the filtered ``render-selection.csv`` writer, the standalone-render argv builder, the
catalog source resolver, and the Export-MP3 gate. All logic lives here; the thin Qt
:mod:`deciwaves.gui.export` panel/worker only add the widgets and threading.

Import-light, exactly like :mod:`deciwaves.gui.library_model`: reads/writes CSVs with the
stdlib ``csv`` module and never imports ``deciwaves.games.*`` (those pull pydecima / heavy
parsers). The per-game render-input schemas are the GUI<->CLI contract (spec §8.1) -- the
columns are preserved byte-for-byte, so this module doesn't need to know them, only the
``line_id`` filter key that every one of them shares.

**The overarching correctness rule (spec §8):** export renders/dumps EXACTLY the checked
rows. The filtered CSV already contains only the checked rows, so every render-side
row-dropping flag is set to include everything: DS renders the filtered playlist straight (no
``--main-story``), HZD keeps all bound rows (no ``--spine-only``), and FW's ``--tiers``
(which FILTERS by tier) is passed the union of every tier actually present so no checked row
is dropped. Per-game render-scope toggles are #73's concern, not this module's.
"""
from __future__ import annotations

import csv
import os

from deciwaves.engine.atomic_io import atomic_write
from deciwaves.gui.cli_command import build_cli_command

# FW render's ``--tiers`` fallback when the filtered manifest carries no tier values at all
# (an empty/degenerate selection -- render then no-ops on empty input anyway). The full set of
# tiers any FW manifest writer ships: "1"/"2" (subtitle-match), "S" (subtitle-bind), "W"
# (weave), "D" (dlc) -- so even the fallback drops nothing. See games/fw/*.py tier constants.
_FW_ALL_TIERS = "1,2,S,W,D"


class ExportError(Exception):
    """An export that cannot proceed, carrying a friendly, user-facing message (a missing
    render-input artifact, or an unconfigured game install). The panel/shell surface the text
    in the log console rather than crashing."""


def _out_dir(workspace: str, game: str) -> str:
    """Artifact root for *game*: ``out/`` for DS, ``out/<game>/`` for HZD/FW (spec §9 #6)."""
    return os.path.join(workspace, "out") if game == "ds" else os.path.join(workspace, "out", game)


def render_input_source(workspace: str, game: str) -> str | None:
    """The path to *game*'s render-input CSV (the file the render stage reads via its
    ``--playlist``/``--manifest`` flag), or ``None`` if it doesn't exist yet.

    Mirrors :func:`library_model.load_lines`'s source precedence for the story-order artifact:
    DS ``out/playlist.csv`` (pre-``order`` -> None), HZD ``out/hzd/asr-manifest.csv``
    (pre-``bind`` -> None), FW ``out/fw/full-reel-manifest.csv`` else
    ``out/fw/subtitle-manifest-full.csv`` (pre-``subtitle-bind`` -> None)."""
    root = _out_dir(workspace, game)
    if game == "ds":
        candidates = ["playlist.csv"]
    elif game == "hzd":
        candidates = ["asr-manifest.csv"]
    elif game == "fw":
        candidates = ["full-reel-manifest.csv", "subtitle-manifest-full.csv"]
    else:
        return None
    for name in candidates:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return None


def can_export_mp3(workspace: str, game: str) -> bool:
    """True iff *game*'s render-input artifact exists on disk -- the gate for Export MP3."""
    return render_input_source(workspace, game) is not None


def render_selection_path(workspace: str, game: str) -> str:
    """``out/<game>/gui/render-selection.csv`` for ALL games (GUI-owned namespace, like
    ``selection.json`` -- even DS, whose pipeline artifacts live in ``out/`` root)."""
    return os.path.join(workspace, "out", game, "gui", "render-selection.csv")


def write_render_selection(workspace: str, game: str, unchecked: set[str]) -> str:
    """Write the filtered render-input CSV (rows = checked lines, columns unchanged) to
    ``out/<game>/gui/render-selection.csv`` and return its absolute path.

    Re-reads the RAW render-input CSV (NOT ``LineRow`` -- the render readers need every
    original column, in order) and keeps only rows whose ``line_id`` is not in *unchecked*.

    Read with ``utf-8-sig`` (transparently strips a BOM a PowerShell-saved source may carry)
    but written **BOM-FREE utf-8**: DS ``story_order.read_playlist`` and HZD ``render._load_csv``
    open plain ``utf-8`` and are BOM-INTOLERANT -- a fused BOM becomes ``\\ufeff`` on the first
    header and KeyErrors the whole read (the recurring #59/#84 bug class). Written atomically
    (``engine.atomic_io``) so an interrupted write can't leave a truncated selection behind.

    Raises :class:`ExportError` if the render-input artifact doesn't exist yet (Export MP3 is
    gated off in that state via :func:`can_export_mp3`)."""
    src = render_input_source(workspace, game)
    if src is None:
        raise ExportError(_missing_source_message(game))
    out_path = render_selection_path(workspace, game)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    unchecked = set(unchecked)

    with open(src, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [r for r in reader if r.get("line_id", "") not in unchecked]

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", newline="", encoding="utf-8") as out:
            # extrasaction="ignore" so a stray extra column in a torn source row (DictReader's
            # restkey) can't crash the write; the declared fieldnames are preserved in order.
            w = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    atomic_write(out_path, _write)
    return out_path


def _missing_source_message(game: str) -> str:
    hint = {"ds": "run `deciwaves ds order` first",
            "hzd": "run `deciwaves hzd bind` first",
            "fw": "run `deciwaves fw subtitle-bind` (or full-reel) first"}.get(game, "run the pipeline first")
    return f"No render input for {game} yet -- {hint}."


def render_selection_argv(base: list[str], workspace: str, game: str, csv_path: str, *,
                          bitrate: int, cfg: dict) -> list[str]:
    """Build the STANDALONE render argv (``deciwaves --workspace <abs> <game> render ...``) that
    renders exactly the rows in *csv_path*.

    Uses :func:`cli_command.build_cli_command`, which inserts ``--workspace <abs>`` BEFORE the
    game token. *csv_path* is passed absolute. Required install flags are pulled from *cfg*
    (``config.load()``) the same way ``cli/run.py`` does; a missing one raises
    :class:`ExportError` (Export MP3 surfaces the text, never crashes). *bitrate* is DS-only
    (HZD/FW are hardcoded 128k, spec §8.2) -- ignored for the other two."""
    csv_abs = os.path.abspath(csv_path)
    if game == "ds":
        data_dir, oodle = _ds_install(cfg)
        # No --main-story: render the filtered playlist straight, so exactly the checked rows
        # render (--main-story would additionally cull side/non-story lines the user kept).
        tokens = ["render", "--playlist", csv_abs, "--data-dir", data_dir,
                  "--oodle", oodle, "--bitrate", str(int(bitrate))]
    elif game == "hzd":
        package = cfg.get("hzd_package")
        if not package:
            raise ExportError("HZD package is not configured. Run `deciwaves setup` first.")
        # No --spine-only: it would drop every checked non-main-quest row.
        tokens = ["render", "--manifest", csv_abs, "--package", package]
    elif game == "fw":
        # --tiers FILTERS by tier; pass the union of every tier present so no checked row is
        # tier-dropped (--audio-root's out/fw default already points at the extracted WAVs).
        tokens = ["render", "--manifest", csv_abs, "--tiers", _fw_tiers(csv_abs),
                  "--uniform-mono"]
    else:
        raise ExportError(f"Export is not supported for game {game!r}.")
    return build_cli_command(base, workspace, game, *tokens)


def _ds_install(cfg: dict) -> tuple[str, str]:
    """``(data_dir, oodle)`` from *cfg*, mirroring cli/run.py's DS resolution (data-dir under
    the install; oodle explicit, else the install's bundled dll). Raises :class:`ExportError`
    if the DS install isn't configured -- render REQUIRES both flags."""
    ds_install = cfg.get("ds_install")
    data_dir = os.path.join(ds_install, "data") if ds_install else None
    oodle = cfg.get("oodle_dll") or (
        os.path.join(ds_install, "oo2core_7_win64.dll") if ds_install else None)
    if not data_dir or not oodle:
        raise ExportError("DS install is not configured. Run `deciwaves setup` first.")
    return data_dir, oodle


def _fw_tiers(csv_path: str) -> str:
    """The comma-joined union of ``tier`` values present in the filtered FW manifest, in
    first-seen order. This is what makes FW's ``--tiers`` render EXACTLY the checked rows:
    every tier that appears among them is included, so ``build_spine``'s tier filter drops
    none. Falls back to the full known tier set only when no tier value is present at all (a
    degenerate/empty selection, which render no-ops on regardless)."""
    tiers: list[str] = []
    try:
        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                t = (r.get("tier") or "").strip()
                if t and t not in tiers:
                    tiers.append(t)
    except OSError:
        pass
    return ",".join(tiers) if tiers else _FW_ALL_TIERS


def catalog_source_path(workspace: str, game: str) -> str | None:
    """The on-disk catalog CSV Export-catalog copies: DS ``out/catalog.csv``, HZD
    ``out/hzd/catalog.csv``; FW has no catalog, so its ``out/fw/clip-index.csv`` (ids + wav
    paths) stands in. ``None`` when the file doesn't exist yet."""
    root = _out_dir(workspace, game)
    name = "clip-index.csv" if game == "fw" else "catalog.csv"
    path = os.path.join(root, name)
    return path if os.path.isfile(path) else None
