"""HZD inventory harvest -- integration test against the real HZDR install (skips if absent)."""
import os
import pytest

HZD_PACKAGE = (r"C:\Program Files (x86)\Steam\steamapps\common"
               r"\Horizon - Zero Dawn Remastered\LocalCacheDX12\package")


@pytest.fixture
def fw():
    if not os.path.isdir(HZD_PACKAGE):
        pytest.skip("HZDR install not present")
    from engine.pack.fw_package import FwPackage
    return FwPackage(HZD_PACKAGE)


def test_harvest_finds_known_sentence_core(fw):
    from games.hzd.inventory import harvest_sentence_cores
    # a bounded scan is enough to surface the known main-quest cutscene core
    paths = harvest_sentence_cores(fw, sample_cap=30000)
    assert "localized/sentences/mq01_papooserider/mq010_cut_namingceremony/sentences" in paths
    # harvested strings are clean (end at a known suffix, no trailing junk)
    assert all(p.endswith(("/sentences", "/simpletext")) for p in paths)
