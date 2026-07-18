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

_READ_ERROR_TAG = "harvest"  # errors-log line prefix for a harvest read failure (issue #66)


def read_error_tag(path_hash: int) -> str:
    """The stable leading (tab-delimited) field of a harvest read-error log line
    (issue #66): ``harvest:<0x-padded-hash>``. Callers dedup on this so a persistent
    failure -- the harvest re-scans the whole pack every run -- is logged once, not
    once per resume (mirrors the FW-extract non-growth contract)."""
    return f"{_READ_ERROR_TAG}:{path_hash:#018x}"


def format_read_error(path_hash: int, exc: BaseException) -> str:
    """One errors-log line for a harvest read failure (issue #66). The single owner of
    the ``harvest:<hash>\\t<Type>: <msg>`` format, shared by catalog and wem-metadata so
    the two logs the GUI issues panel parses (spec §5.4) cannot drift apart. Only the
    ``path_hash`` identifies the core -- the harvest has no path string for it.

    The message is flattened (tab -> space, CR/LF -> space) so an exception whose own
    ``str()`` embeds a tab or newline can't split one failure into a malformed multi-line
    record for the per-line parser (review finding: some OSError/decode messages do)."""
    msg = str(exc).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return f"{read_error_tag(path_hash)}\t{type(exc).__name__}: {msg}\n"


def write_harvest_read_errors(ferr, errors, skip_tags=()) -> None:
    """Write harvest read-error lines to an open errors-log handle (issue #66). The one
    owner of the collector-to-log shape shared by catalog + wem-metadata, so the two
    logs can't diverge (review finding). ``skip_tags`` (a set of ``read_error_tag``
    values) is how catalog's append-mode log skips failures a previous run already
    recorded -- wem-metadata truncates each run and passes nothing."""
    for path_hash, exc in errors:
        if read_error_tag(path_hash) not in skip_tags:
            ferr.write(format_read_error(path_hash, exc))


def harvest_sentence_cores(fw, sample_cap: int | None = None,
                           max_bytes: int = _MAX_BYTES,
                           on_read_error=None) -> list[str]:
    """Return sorted distinct ``localized/sentences/.../{sentences,simpletext}`` paths.

    Parameters
    ----------
    fw:
        An ``engine.pack.hzd_package.HzdPackage``.
    sample_cap:
        If set, stop after scanning this many qualifying ``.core`` records (useful for
        tests / quick runs). ``None`` scans the whole pack.
    on_read_error:
        Optional ``callable(path_hash, exc)`` invoked when a qualifying core's body
        read raises (issue #66). The read is still skipped -- as it always was -- but
        the failure is now surfaced instead of vanishing silently, so callers can log
        and count it (the one drop the GUI issues panel could not otherwise see, spec
        §5.4). ``None`` (the default) preserves the historical silent-skip behavior.
        Only the ``path_hash`` identifies the core here: the whole point of this harvest
        is that HZDR exposes path *hashes*, not strings, for these locator records.
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
        except Exception as exc:
            if on_read_error is not None:
                on_read_error(path_hash, exc)
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
