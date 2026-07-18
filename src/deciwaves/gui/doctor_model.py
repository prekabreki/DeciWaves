"""Qt-free reading of `deciwaves doctor --json` for the Doctor panel (#68, spec §3).

The panel shells out to `doctor --json` (issue #65) so torch/whisperx imports stay in a
child process, then this module turns the payload into rows and decides how each should
read in the UI. The one GUI-specific rule the CLI can't express: the ASR extra and CUDA
are *informational* to the CLI (never fail its exit code), but the GUI **promotes** them
to first-class readiness items for the GPU games (HZD/FW). Branch on ``status`` here, the
same contract the shell's install-status line already uses -- never on message text."""
from __future__ import annotations

import json
from dataclasses import dataclass

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
