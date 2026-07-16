"""HZD-Remastered GameProfile factory.

Usage::

    from deciwaves.games.hzd.profile import build_profile
    profile = build_profile(package_dir=r"...\\LocalCacheDX12\\package")

`package_dir` may be None when the profile is built for classification purposes
only (e.g. tests) -- pack_reader is None in that case.

Unlike DS, HZD does not use pydecima (its FW resources are parsed by the
self-contained games.hzd.sentence_fw), so `decima_version` is informational only.
"""
from __future__ import annotations

import os

from deciwaves.engine.profile import GameProfile

# HZD quest-prefix -> category family (heuristic; see games.hzd.catalog.classify_hzd).
# Matched by longest-prefix on the first scene segment, so "collectab"/"aigenerated"
# win over shorter keys.
HZD_FAMILY_PREFIXES: dict[str, str] = {
    "mq": "main_quest",
    "sq": "side_quest",
    "ec": "errand",
    "dlc": "dlc",
    "collectab": "collectible",
    "aigenerated": "ambient",  # AI-generated ambient/combat barks (the bulk of non-dialogue)
    "shops": "shop",
}

# Short quest codes are always followed by an ID (a digit or "_"): "mq01_", "sq_", "dlc1_".
# They must anchor on that boundary, else "ec"/"sq"/"mq" swallow unrelated words like
# "eclipse"/"square"/"mqueen". The remaining keys are deliberate word-stems
# (e.g. "collectab" is a prefix of "collectables") and keep plain substring matching.
HZD_ANCHORED_PREFIXES: frozenset[str] = frozenset({"mq", "sq", "ec", "dlc"})

# Default narrative transcript for anchor_index building: disabled. The HZD gamescript
# transcript is copyrighted game prose (BYO — see docs/BYO.md), not shipped in this
# repo. "" means story_order.main falls back to episode/scene ordering; pass a real
# path via --transcript (or story_order's own default) to enable anchoring.
HZD_TRANSCRIPT = ""


def hzd_package_error(package_dir: str) -> str | None:
    """Return an actionable error message if *package_dir* doesn't contain
    ``PackFileLocators.bin`` (the file ``FwPackage``/``FwLocators`` need), else
    ``None``. Kept separate from ``build_profile`` so the missing-file message
    is unit-testable without a real install (mirrors
    ``games.fw.subtitle_bind.types_json_error``).

    Without this check, a wrong --package (e.g. the game install root instead
    of ...\\LocalCacheDX12\\package) surfaced only as a raw FileNotFoundError
    traceback from engine.pack.fw_locators at catalog time (issue #34).
    """
    if os.path.isfile(os.path.join(package_dir, "PackFileLocators.bin")):
        return None
    return (
        f"HZD package not found: no PackFileLocators.bin under {package_dir}. "
        "This must be the ...\\LocalCacheDX12\\package directory (the one "
        "containing PackFileLocators.bin), not the game install root. Fix: "
        "re-run `deciwaves setup --hzd-package <...\\LocalCacheDX12\\package>` "
        "(or pass the correct --package directly to this stage)."
    )


def build_profile(package_dir: str | None) -> GameProfile:
    """Build and return the HZD GameProfile.

    Parameters
    ----------
    package_dir:
        Path to the HZDR ``LocalCacheDX12/package`` directory (passed to
        FwPackage).  May be None when pack_reader is not needed.
    """
    if package_dir is not None:
        from deciwaves.engine.pack.fw_package import FwPackage
        pack_reader = FwPackage(package_dir)
    else:
        pack_reader = None

    return GameProfile(
        name="hzd",
        pack_reader=pack_reader,
        decima_version="HZDR",  # informational: HZD parse does not use pydecima
        core_prefixes=HZD_FAMILY_PREFIXES,
        speaker_simpletext_filter=lambda p: (
            "sentences/voices/" in p and p.strip().endswith("/simpletext")
        ),
        transcript_path=HZD_TRANSCRIPT,
        out_dir="out/hzd",
    )
