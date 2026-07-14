import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hzd_phys_to_key as p2k

HZD_PACKAGE = Path(p2k.DEFAULT_PACKAGE)
ORACLE_KEY = 0x3E0F9D4305030200
ORACLE_OFFSET = 133081218  # logical offset of the oracle clip in pkg01 stream


@pytest.fixture
def require_hzd_install():
    if not (HZD_PACKAGE / "PackFileLocators.bin").is_file():
        pytest.skip("HZD Remastered install not present")
    return str(HZD_PACKAGE)


def test_oracle_physical_offset_round_trips_to_its_key(require_hzd_install):
    entries, dsar = p2k.load(require_hzd_install, p2k.DEFAULT_ARCHIVE)
    # forward: the oracle's logical offset sits in some DSAR chunk; that chunk's
    # physical (compressed) offset is what DirectStorage would read.
    coffs = [c.offset for c in dsar._chunks]
    from bisect import bisect_right
    ci = bisect_right(coffs, ORACLE_OFFSET) - 1
    phys = dsar._chunks[ci].compressed_offset
    # reverse: that physical offset must resolve back to the oracle key.
    keys = p2k.phys_to_keys(entries, dsar, phys)
    assert ORACLE_KEY in keys
