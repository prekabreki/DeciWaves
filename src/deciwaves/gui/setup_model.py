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

from deciwaves.cli.config import TOOLS
from deciwaves.gui.doctor_model import (
    SEV_ERROR,
    SEV_NEUTRAL,
    SEV_OK,
    SEV_WARN,
    STATUS_BROKEN,
    STATUS_OK,
    DoctorItem,
)

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


# setup's summary label ("vgmstream") -> doctor's check name ("vgmstream-cli"), so a setup
# tool row can be reconciled against the matching `doctor --json` check (#110).
_SETUP_TO_DOCTOR = {t.key: t.display for t in TOOLS}


def tool_severity(row: SetupRow, doctor_items: list[DoctorItem]) -> str:
    """Severity for a setup tool row, reconciled against doctor's verdict (#110).

    Doctor is authoritative on a tool's actual state, so the two panels can never show the
    same tool red-and-green at once -- in *either* direction:

    - a FAILED-to-refetch tool that doctor confirms present + valid is a warning ("using
      existing copy"), not a hard error;
    - a "fetched" tool that doctor reports broken (AV-quarantined, wrong arch) is an error,
      not a green tick.

    Doctor's own ``ok`` flag is True even for optional not_configured/unavailable checks, so
    this gates on the concrete ``status`` (``ok``/``broken``), never on ``ok`` alone. When
    doctor has no opinion on the tool the setup row's own state stands."""
    name = _SETUP_TO_DOCTOR.get(row.label)
    doc = next((d for d in doctor_items if d.name == name), None)
    if row.ok:
        return SEV_ERROR if (doc is not None and doc.status == STATUS_BROKEN) else SEV_OK
    if not row.failed:
        return SEV_NEUTRAL
    return SEV_WARN if (doc is not None and doc.status == STATUS_OK) else SEV_ERROR
