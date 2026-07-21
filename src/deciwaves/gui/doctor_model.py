"""Qt-free reading of `deciwaves doctor --json` for the Doctor panel (#68, spec §3).

The panel shells out to `doctor --json` (issue #65) so torch/whisperx imports stay in a
child process, then this module turns the payload into rows and decides how each should
read in the UI. The one GUI-specific rule the CLI can't express: the ASR extra and CUDA
are *informational* to the CLI (never fail its exit code), but the GUI **promotes** them
to first-class readiness items for the GPU games (HZD/FW). Branch on ``status`` here, the
same contract the shell's install-status line already uses -- never on message text.

The module also provides the Qt-free helper ``install_status_attrs`` for the global-bar's
install-status line (issue #122): maps a doctor ``Availability`` to a (glyph, colour)
pair, so the widget never has to know about the enum."""
from __future__ import annotations

import json
from dataclasses import dataclass

from deciwaves.cli.doctor import Availability

# doctor.Availability.value strings, as they appear in each check's "status" field.
STATUS_OK = "ok"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_BROKEN = "broken"
STATUS_UNAVAILABLE = "unavailable"

# GUI-side severities the panel renders (colour/icon), distinct from the CLI's status.
SEV_OK = "ok"
SEV_ERROR = "error"
SEV_WARN = "warn"
SEV_NEUTRAL = "neutral"

# Glyph + colour for each Availability, used by the global-bar install-status line.
_GLYPH_OK = "✓"
_GLYPH_NEUTRAL = "—"
_GLYPH_ERROR = "✗"

# Colour hex values (mirror theme.py; kept here so the helper is Qt-free).
_COLOR_OK = "#167f3b"
_COLOR_NEUTRAL = "#666666"
_COLOR_ERROR = "#b00020"

def install_status_attrs(status: Availability) -> tuple[str, str]:
    """Map a doctor ``Availability`` to (glyph, hex-colour) for the global bar.

    Mirrors the Doctor panel's severity rule (``NOT_CONFIGURED`` → neutral grey,
    never red) so an unowned game doesn't read as broken (issue #122)."""
    if status is Availability.OK:
        return (_GLYPH_OK, _COLOR_OK)
    if status is Availability.NOT_CONFIGURED:
        return (_GLYPH_NEUTRAL, _COLOR_NEUTRAL)
    if status is Availability.BROKEN:
        return (_GLYPH_ERROR, _COLOR_ERROR)
    return (_GLYPH_NEUTRAL, _COLOR_NEUTRAL)


# Checks the GUI promotes to first-class readiness for the GPU games (spec §3).
_GPU_READINESS = frozenset({"asr_extra", "cuda"})
_GPU_GAMES = frozenset({"hzd", "fw"})


@dataclass(frozen=True)
class DoctorItem:
    """One `doctor --json` check, keyed exactly as ``Check.as_json()`` emits it."""

    name: str
    ok: bool
    status: str
    message: str
    fix: str


def load_doctor_payload(text: str) -> dict | None:
    """Extract the ``doctor --json`` object from a subprocess's stdout, or None.

    stdout is NOT guaranteed to be pure JSON: ``config.load()`` prints a corruption
    warning to stdout, and a GPU stack can emit import banners -- both land *before*
    doctor's ``json.dumps`` output. So fall back from a whole-string parse to the last
    ``{...}`` block, and reject valid-but-non-object JSON (a bare array/number)."""
    for candidate in (text, _last_brace_block(text)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _last_brace_block(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else ""


def parse_doctor_payload(payload: dict) -> list[DoctorItem]:
    return [
        DoctorItem(
            name=c["name"],
            ok=bool(c.get("ok", False)),
            status=c.get("status", ""),
            message=c.get("message", ""),
            fix=c.get("fix", ""),
        )
        for c in payload.get("checks", [])
    ]


def overall_ok(payload: dict) -> bool:
    """The CLI's own AND-of-every-check pass/fail (agrees with the process exit code)."""
    return bool(payload.get("ok", False))


def severity(item: DoctorItem, game: str) -> str:
    """How this check should read for the currently selected ``game``."""
    if item.status == STATUS_BROKEN:
        return SEV_ERROR
    if item.status == STATUS_NOT_CONFIGURED:
        return SEV_NEUTRAL  # unowned/unconfigured -> neutral, never a failure (spec §3)
    # The GPU extras are first-class readiness ONLY for the GPU games; for DS (no GPU
    # stage in its default chain) they stay purely informational -- neutral whether
    # present or absent, never a green readiness tick (spec §3).
    if item.name in _GPU_READINESS and game not in _GPU_GAMES:
        return SEV_NEUTRAL
    if item.status == STATUS_OK:
        return SEV_OK
    # UNAVAILABLE (or anything else): a real readiness gap for a promoted GPU extra on a
    # GPU game; otherwise just informational.
    if item.name in _GPU_READINESS and game in _GPU_GAMES:
        return SEV_WARN
    return SEV_NEUTRAL


def pill_for(item: DoctorItem, game: str) -> tuple[str, str] | None:
    """A ``(label, tone)`` badge for a Doctor row, or None for a plain row.

    Makes the per-game optional-vs-required framing unmissable (#112): the GPU
    extras (CUDA / ASR) read as an explicit "Optional" pill for a non-GPU game
    like DS instead of a bare grey dash, and a genuinely broken required tool
    reads as "Needed"."""
    if item.name in _GPU_READINESS and game not in _GPU_GAMES:
        return ("Optional", "optional")
    if severity(item, game) == SEV_ERROR:
        return ("Needed", "needed")
    return None
