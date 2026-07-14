# tests/test_pack_index.py
from deciwaves.engine.pack.bin_index import PackIndex
from conftest import DATA_DIR, OODLE_DLL, FIXTURE_PR201

PR201 = "localized/sentences/ds_lines_terminal/lines_pr201/sentences"


def test_read_core_matches_fixture(require_install, pr201_core_bytes):
    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    data = idx.read_core(PR201)
    assert data == pr201_core_bytes  # byte-exact vs Phase-A extraction


def test_missing_core_raises(require_install):
    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    import pytest
    with pytest.raises(KeyError):
        idx.read_core("localized/sentences/does_not_exist/sentences")
