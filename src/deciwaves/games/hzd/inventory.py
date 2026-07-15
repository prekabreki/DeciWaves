"""HZD inventory: harvest sentence/voice core virtual paths by content-scanning the pack.

HZDR's PackFileLocators.bin exposes only path-*hashes*, not path strings, so we cannot
enumerate sentence cores by name directly. But `.core` bodies embed readable
length-prefixed virtual-path strings (an FW-engine-era resource trait), so we recover the
paths by scanning core bodies for `localized/sentences/...` substrings. See
docs/architecture.md for how this fits the HZD extraction pipeline.

Coverage caveat: this finds every sentence-core path that is embedded as a string in some
core (sentence cores are referenced by higher-level cores). A core addressed *only* by
hash, with its path string nowhere embedded, would be missed -- the best achievable without
an external path-list (odradek, the community HFW/DS2 RE tool, has no HZD Remastered support).
"""
from __future__ import annotations
import re

_PATH_RE = re.compile(rb"localized/sentences/[ -~]{3,200}")
_SUFFIXES = ("/sentences", "/simpletext")
_PREFIX_LEN = len("localized/sentences/")  # skip the prefix's own "/sentences" when cutting
_MAX_BYTES = 2_000_000  # skip textures/large bundles; sentence cores are far smaller


def harvest_sentence_cores(fw, sample_cap: int | None = None,
                           max_bytes: int = _MAX_BYTES) -> list[str]:
    """Return sorted distinct ``localized/sentences/.../{sentences,simpletext}`` paths.

    Parameters
    ----------
    fw:
        An ``engine.pack.fw_package.FwPackage``.
    sample_cap:
        If set, stop after scanning this many qualifying ``.core`` records (useful for
        tests / quick runs). ``None`` scans the whole pack.
    """
    found: set[str] = set()
    scanned = 0
    for path_hash, loc in fw.locators.items():
        if loc.archive.endswith(".stream") or loc.length > max_bytes or loc.length < 12:
            continue
        if sample_cap is not None and scanned >= sample_cap:
            break
        scanned += 1
        try:
            raw = fw.read_by_hash(path_hash)
        except Exception:
            continue
        for m in _PATH_RE.finditer(raw):
            s = m.group().decode("ascii", "replace")
            # the regex may capture trailing bytes past the path; cut at the terminal
            # suffix. Search past the prefix's own "/sentences" (in "localized/sentences/")
            # and take the earliest terminal so concatenated captures split cleanly.
            ends = [s.find(suf, _PREFIX_LEN) + len(suf)
                    for suf in _SUFFIXES if s.find(suf, _PREFIX_LEN) != -1]
            if ends:
                found.add(s[: min(ends)])
    return sorted(found)
