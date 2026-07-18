"""Qt-free `deciwaves setup` argv construction + summary/warning parsing (#68, spec §3,§4).

Setup is game-free (no ``--workspace``/game token, unlike ``cli_command.build_cli_command``),
so it gets its own builder. Path flags follow the GUI's always-absolute discipline (spec §4)
with one exception: an explicit ``""`` is the CLI's "clear this saved value" signal and must
reach setup verbatim. There is no machine-readable setup mode, so the summary is parsed from
setup's human text -- keyed by its known labels rather than by column position, because a tool
status can be longer than the summary's padded column (e.g. "found (skipped -- ...)")."""
from __future__ import annotations

import os
from dataclasses import dataclass

# Labels setup prints in its summary (setup._print_summary): the three fetched tools plus
# the derived path rows. Used to pick summary lines out of the surrounding chatter.
_TOOL_LABELS = ("vgmstream", "VGAudio", "ffmpeg")
_PATH_LABELS = ("ds_install", "oodle_dll", "hzd_pkg", "fw_pkg", "fw_script")
_SUMMARY_LABELS = frozenset(_TOOL_LABELS + _PATH_LABELS)

_OK_PREFIXES = ("ok", "found", "fetched")


@dataclass(frozen=True)
class SetupRow:
    label: str
    detail: str  # the status + path remainder, verbatim (status may contain spaces)
    ok: bool
    failed: bool


def build_setup_argv(base: list[str], *, force: bool = False, skip_downloads: bool = False,
                     ds_install: str | None = None, hzd_package: str | None = None,
                     fw_package: str | None = None, fw_gamescript: str | None = None,
                     fw_types: str | None = None, tools_dir: str | None = None) -> list[str]:
    """``base + setup + flags``. A ``None`` path is omitted (setup keeps the saved value);
    ``""`` is passed through to clear it; any real path is absolutized (spec §4)."""
    argv = [*base, "setup"]
    if force:
        argv.append("--force")
    if skip_downloads:
        argv.append("--skip-downloads")
    for flag, val in (("--ds-install", ds_install), ("--hzd-package", hzd_package),
                      ("--fw-package", fw_package), ("--fw-gamescript", fw_gamescript),
                      ("--fw-types", fw_types), ("--tools-dir", tools_dir)):
        if val is None:
            continue
        argv.extend([flag, "" if val == "" else os.path.abspath(val)])
    return argv


def parse_setup_summary(text: str) -> list[SetupRow]:
    """One :class:`SetupRow` per known summary label found in setup's stdout."""
    rows: list[SetupRow] = []
    for line in text.splitlines():
        if not line.startswith("  "):
            continue
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or parts[0] not in _SUMMARY_LABELS:
            continue
        label, detail = parts[0], parts[1].strip()
        first = detail.split(None, 1)[0]
        failed = first == "MISSING" or detail.startswith("FAILED")
        rows.append(SetupRow(label=label, detail=detail,
                             ok=first in _OK_PREFIXES, failed=failed))
    return rows


def parse_setup_warnings(text: str) -> list[str]:
    """The verbatim ``WARNING:`` lines setup emits (Oodle-not-located, HZD path hints)."""
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("WARNING:")]
