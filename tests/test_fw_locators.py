import os
import struct
from pathlib import Path

import pytest
from deciwaves.engine.pack.fw_locators import FwLocators, Locator, Entry


def _build_locators(packfiles):
    """packfiles: list of (name, [(hash, offset, length), ...])."""
    out = struct.pack("<I", len(packfiles))
    for name, records in packfiles:
        nb = name.encode("utf-8")
        out += struct.pack("<I", len(nb)) + nb + struct.pack("<I", len(records))
        for h, off, length in records:
            out += struct.pack("<QII", h, off, length)
    return out


def test_parse_and_lookup():
    data = _build_locators([
        ("package.00.00.core", [(0xAABB, 0, 100), (0xCCDD, 128, 256)]),
        ("package.00.01.core", [(0x1234, 64, 512)]),
    ])
    loc = FwLocators.from_bytes(data)
    assert loc.archives == ["package.00.00.core", "package.00.01.core"]
    assert len(loc) == 3
    assert loc.lookup(0xCCDD) == Locator("package.00.00.core", 128, 256)
    assert loc.lookup(0x1234) == Locator("package.00.01.core", 64, 512)
    assert 0xAABB in loc


def test_lookup_miss_returns_none():
    loc = FwLocators.from_bytes(_build_locators([("a.core", [(1, 0, 1)])]))
    assert loc.lookup(0xDEAD) is None
    assert 0xDEAD not in loc


def test_ordered_entries_preserve_file_order_and_duplicates():
    # 0xBB appears in both archives: the dict view must dedupe (first wins),
    # but the ordered view must keep every record, in raw file order. Needed
    # to test positional pairing of .core.stream entries against .core entries.
    data = _build_locators([
        ("a.core", [(0xAA, 0, 10), (0xBB, 16, 20)]),
        ("b.core.stream", [(0xBB, 0, 30), (0xCC, 64, 40)]),
    ])
    loc = FwLocators.from_bytes(data)
    assert loc.lookup(0xBB) == Locator("a.core", 16, 20)  # dict still dedupes
    assert loc.entries() == [
        Entry("a.core", 0xAA, 0, 10),
        Entry("a.core", 0xBB, 16, 20),
        Entry("b.core.stream", 0xBB, 0, 30),
        Entry("b.core.stream", 0xCC, 64, 40),
    ]
    assert loc.entries("b.core.stream") == [
        Entry("b.core.stream", 0xBB, 0, 30),
        Entry("b.core.stream", 0xCC, 64, 40),
    ]


def test_items_dedupes_first_wins():
    # 0xBB duplicated across archives: items() must expose only the deduped,
    # first-packfile-wins view (the public counterpart to iterating the
    # internal hash table directly -- see games/hzd/inventory.py, issue #27).
    data = _build_locators([
        ("a.core", [(0xAA, 0, 10), (0xBB, 16, 20)]),
        ("b.core.stream", [(0xBB, 0, 30), (0xCC, 64, 40)]),
    ])
    loc = FwLocators.from_bytes(data)
    items = loc.items()
    assert dict(items) == {
        0xAA: Locator("a.core", 0, 10),
        0xBB: Locator("a.core", 16, 20),  # first archive wins, matches lookup()
        0xCC: Locator("b.core.stream", 64, 40),
    }
    assert len(items) == len(loc)


def test_trailing_garbage_raises():
    """Unexpected bytes after the last parsed record must not be silently
    ignored -- a truncated/corrupted PackFileLocators.bin should fail loudly,
    not silently under-read."""
    data = _build_locators([("a.core", [(0xAA, 0, 10)])]) + b"\x01\x02\x03"
    with pytest.raises(ValueError, match="3"):
        FwLocators.from_bytes(data)


def test_no_trailing_garbage_does_not_raise():
    data = _build_locators([("a.core", [(0xAA, 0, 10), (0xBB, 16, 20)])])
    FwLocators.from_bytes(data)  # must not raise


def test_duplicate_count_reflects_collapsed_duplicates():
    # 0xBB appears in both archives -> one duplicate collapsed by the dict.
    data = _build_locators([
        ("a.core", [(0xAA, 0, 10), (0xBB, 16, 20)]),
        ("b.core.stream", [(0xBB, 0, 30), (0xCC, 64, 40)]),
    ])
    loc = FwLocators.from_bytes(data)
    assert loc.duplicate_count == 1
    assert len(loc.entries()) - len(loc) == loc.duplicate_count


def test_duplicate_count_zero_when_no_duplicates():
    data = _build_locators([("a.core", [(0xAA, 0, 10), (0xBB, 16, 20)])])
    loc = FwLocators.from_bytes(data)
    assert loc.duplicate_count == 0


# Override with DECIWAVES_HZD_PACKAGE, mirroring the DECIWAVES_DS_INSTALL /
# DECIWAVES_FW_INSTALL convention (see conftest.py).
HZD_PACKAGE = Path(os.environ.get(
    "DECIWAVES_HZD_PACKAGE",
    r"C:\Program Files (x86)\Steam\steamapps\common\Horizon - Zero Dawn Remastered\LocalCacheDX12\package"))


@pytest.fixture
def require_hzd_install():
    if not (HZD_PACKAGE / "PackFileLocators.bin").is_file():
        pytest.skip("HZD Remastered install not present")
    return HZD_PACKAGE


def test_real_locators(require_hzd_install):
    loc = FwLocators(str(require_hzd_install / "PackFileLocators.bin"))
    assert loc.archives[0] == "package.00.00.core"
    assert len(loc.archives) == 78           # NumPackfiles observed 2026-06-26
    assert all(a.startswith("package.") for a in loc.archives)
    assert len(loc) > 1000                    # many indexed resources
