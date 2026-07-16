"""HZD inventory harvest -- integration test against the real HZDR install (skips if absent),
plus hermetic unit tests against a fake FwPackage-like stand-in (issue #27: harvest_sentence_cores
must only use the public `fw.locators` / `fw.read_by_hash` surface, not reach into
`fw._locators._by_hash`)."""
import os
import pytest

from deciwaves.engine.pack.bin_archive import file_hash
from deciwaves.engine.pack.fw_locators import FwLocators

# Override with DECIWAVES_HZD_PACKAGE, mirroring the DECIWAVES_DS_INSTALL /
# DECIWAVES_FW_INSTALL convention (see conftest.py) and the sibling pack tests
# (test_dsar_archive.py / test_fw_locators.py / test_fw_package.py). Falls back
# to the old literal so behavior is unchanged when unset; the fixture skips
# cleanly when the path is absent.
HZD_PACKAGE = os.environ.get(
    "DECIWAVES_HZD_PACKAGE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package")


@pytest.fixture
def fw():
    if not os.path.isdir(HZD_PACKAGE):
        pytest.skip("HZDR install not present")
    from deciwaves.engine.pack.fw_package import FwPackage
    return FwPackage(HZD_PACKAGE)


def test_harvest_finds_known_sentence_core(fw):
    from deciwaves.games.hzd.inventory import harvest_sentence_cores
    # a bounded scan is enough to surface the known main-quest cutscene core
    paths = harvest_sentence_cores(fw, sample_cap=30000)
    assert "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences" in paths
    # harvested strings are clean (end at a known suffix, no trailing junk)
    assert all(p.endswith(("/sentences", "/simpletext")) for p in paths)


# ---------------------------------------------------------------------------
# Hermetic unit tests: a minimal fake standing in for FwPackage, exposing only
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


class _FakeFwPackage:
    """Stand-in exposing only what harvest_sentence_cores uses: `.locators` (a real
    FwLocators, built from synthetic bytes) and `.read_by_hash(hash) -> bytes`."""

    def __init__(self, locators: FwLocators, blobs: dict[int, bytes]):
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
    return _FakeFwPackage(FwLocators.from_bytes(data), blobs)


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
