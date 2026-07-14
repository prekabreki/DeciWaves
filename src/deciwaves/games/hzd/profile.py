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
# "eclipse"/"square"/"mqueen" (#43). The remaining keys are deliberate word-stems
# (e.g. "collectab" is a prefix of "collectables") and keep plain substring matching.
HZD_ANCHORED_PREFIXES: frozenset[str] = frozenset({"mq", "sq", "ec", "dlc"})

HZD_TRANSCRIPT = "docs/zero_dawn_gamescript.md"


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
