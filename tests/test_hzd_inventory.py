"""HZD inventory harvest -- integration test against the real HZDR install (skips if absent),
plus hermetic unit tests against a fake HzdPackage-like stand-in (issue #27: harvest_sentence_cores
must only use the public `fw.locators` / `fw.read_by_hash` surface, not reach into
`fw._locators._by_hash`)."""
import os
import pytest

from deciwaves.engine.pack.bin_archive import file_hash
from deciwaves.engine.pack.hzd_locators import HzdLocators

from conftest import HZD_PACKAGE


@pytest.fixture
def fw():
    if not os.path.isdir(HZD_PACKAGE):
        pytest.skip("HZDR install not present")
    from deciwaves.engine.pack.hzd_package import HzdPackage
    return HzdPackage(str(HZD_PACKAGE))


def test_harvest_finds_known_sentence_core(fw):
    from deciwaves.games.hzd.inventory import harvest_sentence_cores
    # a bounded scan is enough to surface the known main-quest cutscene core
    paths = harvest_sentence_cores(fw, sample_cap=30000)
    assert "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences" in paths
    # harvested strings are clean (end at a known suffix, no trailing junk)
    assert all(p.endswith(("/sentences", "/simpletext")) for p in paths)


# ---------------------------------------------------------------------------
# Hermetic unit tests: a minimal fake standing in for HzdPackage, exposing only
# the public surface harvest_sentence_cores actually needs (`.locators` /
# `.read_by_hash`). No real install, DSAR archive, or lz4 needed.
# ---------------------------------------------------------------------------

def _build_locators_bytes(packfiles):
    """packfiles: list of (name, [(hash, offset, length), ...]) -> PackFileLocators.bin bytes."""
    import struct
    out = struct.pack("<I", len(packfiles))
    for name, records in packfiles:
        nb = name.encode("utf-8")
        out += struct.pack("<I", len(nb)) + nb + struct.pack("<I", len(records))
        for h, off, length in records:
            out += struct.pack("<QII", h, off, length)
    return out


class _FakeHzdPackage:
    """Stand-in exposing only what harvest_sentence_cores uses: `.locators` (a real
    HzdLocators, built from synthetic bytes) and `.read_by_hash(hash) -> bytes`."""

    def __init__(self, locators: HzdLocators, blobs: dict[int, bytes]):
        self.locators = locators
        self._blobs = blobs

    def read_by_hash(self, path_hash: int) -> bytes:
        return self._blobs[path_hash]


def _make_fake_fw(entries):
    """entries: list of (archive_name, recorded_length, payload_bytes).
    Hashes a synthetic per-entry virtual path so each gets a distinct path_hash;
    the recorded length in the locator can differ from len(payload) so filtering
    by locator metadata can be tested independently of actual payload size."""
    packfiles = {}
    blobs = {}
    for i, (archive, recorded_length, payload) in enumerate(entries):
        vpath = f"synthetic/entry_{i}.core"
        h = file_hash(vpath)
        packfiles.setdefault(archive, []).append((h, 0, recorded_length))
        blobs[h] = payload
    data = _build_locators_bytes(list(packfiles.items()))
    return _FakeHzdPackage(HzdLocators.from_bytes(data), blobs)


def test_harvest_finds_embedded_sentence_path():
    from deciwaves.games.hzd.inventory import harvest_sentence_cores

    payload = b"localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences\x00pad"
    fw = _make_fake_fw([("a.core", len(payload), payload)])
    assert harvest_sentence_cores(fw) == [
        "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences"
    ]


def test_harvest_skips_stream_archives():
    from deciwaves.games.hzd.inventory import harvest_sentence_cores

    payload = b"localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences\x00pad"
    fw = _make_fake_fw([("a.core.stream", len(payload), payload)])
    assert harvest_sentence_cores(fw) == []


def test_harvest_skips_oversized_and_undersized_by_locator_length():
    from deciwaves.games.hzd.inventory import harvest_sentence_cores

    payload = b"localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences\x00pad"
    too_big = _make_fake_fw([("a.core", 2_000_001, payload)])
    assert harvest_sentence_cores(too_big) == []

    too_small = _make_fake_fw([("a.core", 11, payload)])
    assert harvest_sentence_cores(too_small) == []


# ---------------------------------------------------------------------------
# Read-failure observability (issue #66): a core whose body read raises must not
# vanish silently -- the harvester reports it through an on_read_error callback so
# callers can log + count it (the one drop the GUI issues panel couldn't see).
# ---------------------------------------------------------------------------

class _RaisingFakeHzdPackage(_FakeHzdPackage):
    """A fake whose read_by_hash raises for a designated set of path hashes."""

    def __init__(self, locators, blobs, raise_for):
        super().__init__(locators, blobs)
        self._raise_for = raise_for

    def read_by_hash(self, path_hash: int) -> bytes:
        if path_hash in self._raise_for:
            raise OSError(f"boom {path_hash:#x}")
        return super().read_by_hash(path_hash)


def test_harvest_invokes_on_read_error_for_unreadable_cores():
    from deciwaves.games.hzd.inventory import harvest_sentence_cores

    good = b"localized/sentences/mq01_x/mq010_cut/sentences\x00pad"
    base = _make_fake_fw([("a.core", len(good), good), ("b.core", 64, b"x" * 64)])
    bad_hash = file_hash("synthetic/entry_1.core")
    fw = _RaisingFakeHzdPackage(base.locators, base._blobs, {bad_hash})

    seen: list[tuple[int, Exception]] = []
    paths = harvest_sentence_cores(fw, on_read_error=lambda h, e: seen.append((h, e)))

    # the readable core is still harvested; the unreadable one is reported, not dropped
    assert paths == ["localized/sentences/mq01_x/mq010_cut/sentences"]
    assert len(seen) == 1
    assert seen[0][0] == bad_hash
    assert isinstance(seen[0][1], OSError)


def test_harvest_without_callback_still_skips_unreadable_cores():
    """Backward compatibility: no callback => a failed read is skipped silently
    (today's behavior), never propagated as a crash."""
    from deciwaves.games.hzd.inventory import harvest_sentence_cores

    good = b"localized/sentences/mq01_x/mq010_cut/sentences\x00pad"
    base = _make_fake_fw([("a.core", len(good), good), ("b.core", 64, b"x" * 64)])
    bad_hash = file_hash("synthetic/entry_1.core")
    fw = _RaisingFakeHzdPackage(base.locators, base._blobs, {bad_hash})

    assert harvest_sentence_cores(fw) == ["localized/sentences/mq01_x/mq010_cut/sentences"]


def test_format_read_error_is_a_single_tab_safe_line():
    """The errors log is tab-delimited (field) and newline-delimited (record), parsed
    per line by the GUI issues panel (spec §5.4). An exception message that itself
    embeds a tab/newline must not split one failure into a malformed multi-line record
    (review finding #2)."""
    from deciwaves.games.hzd.inventory import format_read_error

    line = format_read_error(0x1234, ValueError("bad\nmulti\tline\r\n"))
    assert line.endswith("\n") and line.count("\n") == 1   # exactly one physical record
    assert "\r" not in line
    assert line.count("\t") == 1                            # only the field delimiter
    assert line.startswith("harvest:0x")
    assert "ValueError" in line and "bad multi line" in line  # message preserved, flattened


def test_write_harvest_read_errors_dedups_by_skip_tags():
    """The shared writer (single owner of the collector/write format across catalog +
    wem-metadata, review finding #3) skips any error whose tag is in skip_tags -- how
    catalog's append-mode log avoids growing across resumes."""
    import io
    from deciwaves.games.hzd.inventory import (
        write_harvest_read_errors, read_error_tag,
    )

    buf = io.StringIO()
    errors = [(0x1111, OSError("a")), (0x2222, ValueError("b"))]
    write_harvest_read_errors(buf, errors, skip_tags={read_error_tag(0x1111)})
    out = buf.getvalue()
    assert read_error_tag(0x2222) in out
    assert read_error_tag(0x1111) not in out   # already logged -> skipped

    buf2 = io.StringIO()
    write_harvest_read_errors(buf2, errors)     # no skips -> both written
    assert buf2.getvalue().count("harvest:") == 2
