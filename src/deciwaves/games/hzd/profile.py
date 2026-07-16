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

# The DSAR archive holding every dialogue clip's encoded ATRAC9 payload -- shared by
# every stage that decodes or fingerprints clips (clip_index, asr_bind, render).
VOICE_ARCHIVE = "package.01.00.core.stream"


HZD_LOCATORS_NAME = "PackFileLocators.bin"


def is_valid_hzd_package_dir(package_dir: str) -> bool:
    """True iff *package_dir* directly contains ``PackFileLocators.bin`` -- the
    one shape check for "does this look like the HZDR
    ...\\LocalCacheDX12\\package directory", shared by ``cli.doctor``'s
    ``check_hzd_package``, ``cli.setup``'s ``_hzd_package_warning``, and this
    module's own ``hzd_package_error`` (previously each independently
    reimplemented the same ``os.path.isfile(os.path.join(dir,
    "PackFileLocators.bin"))`` check -- issue #51 item 2). Each caller keeps
    its own message wording: a doctor preflight status line, a setup WARNING
    with an install-root-typo suggestion, and this module's stage-time hard
    error are genuinely different audiences, so only the predicate and the
    filename constant are unified here.
    """
    return os.path.isfile(os.path.join(package_dir, HZD_LOCATORS_NAME))


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
    if is_valid_hzd_package_dir(package_dir):
        return None
    return (
        f"HZD package not found: no PackFileLocators.bin under {package_dir}. "
        "This must be the ...\\LocalCacheDX12\\package directory (the one "
        "containing PackFileLocators.bin), not the game install root. Fix: "
        "re-run `deciwaves setup --hzd-package <...\\LocalCacheDX12\\package>` "
        "(or pass the correct --package directly to this stage)."
    )


def locators_fingerprint(package_dir: str) -> str:
    """Cheap ``size:mtime_ns`` fingerprint of ``<package_dir>/PackFileLocators.bin``.

    Used to detect a stale ``catalog-cores.txt`` sidecar (issue #45): any game patch
    that adds/moves/removes dialogue cores rewrites the locator index, so a changed
    fingerprint is a sufficient (and much cheaper than re-hashing the whole pack)
    signal that a previously-harvested core-path list may no longer match the pack.
    Raises the same way ``os.stat`` would if *package_dir* doesn't contain the file --
    callers that need an actionable message first check ``hzd_package_error``.
    """
    st = os.stat(os.path.join(package_dir, "PackFileLocators.bin"))
    return f"{st.st_size}:{st.st_mtime_ns}"


def cores_sidecar_header(package_dir: str) -> str:
    """Comment header line stamped into the ``catalog-cores.txt`` sidecar's first line
    (via ``engine.catalog_io.write_core_paths_sidecar``'s ``header=``), recording
    ``locators_fingerprint(package_dir)`` at write time. ``games.hzd.wem_metadata`` reads
    it back (``read_core_paths_sidecar_header``) to detect a sidecar harvested from a
    pack that has since been patched (issue #45). One shared place so the writer
    (``games.hzd.catalog``) and reader (``games.hzd.wem_metadata``) can never drift on
    the header's format.
    """
    return f"# locators: {locators_fingerprint(package_dir)}"


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
        pack_reader=pack_reader,
        decima_version="HZDR",  # informational: HZD parse does not use pydecima
        core_prefixes=HZD_FAMILY_PREFIXES,
        speaker_simpletext_filter=lambda p: (
            "sentences/voices/" in p and p.strip().endswith("/simpletext")
        ),
    )
