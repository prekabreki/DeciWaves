# tests/test_pack_index.py
import pytest

from deciwaves.engine.pack.bin_index import PackIndex
from deciwaves.engine.pack.bin_archive import file_hash
from conftest import DATA_DIR, OODLE_DLL

PR201 = "localized/sentences/ds_lines_terminal/lines_pr201/sentences"


def test_read_core_matches_fixture(require_install, pr201_core_bytes):
    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    data = idx.read_core(PR201)
    assert data == pr201_core_bytes  # byte-exact vs Phase-A extraction


def test_missing_core_raises(require_install):
    idx = PackIndex(str(DATA_DIR), str(OODLE_DLL))
    with pytest.raises(KeyError):
        idx.read_core("localized/sentences/does_not_exist/sentences")


# ---------------------------------------------------------------------------
# has() / read_by_hash() -- hermetic unit tests over a fake index (issue #27).
# No real install/Oodle needed: we bypass __init__ and stub the (archive, entry)
# pairs directly, exactly mirroring what open_index() would have populated.
# ---------------------------------------------------------------------------

class _FakeArchive:
    """Stand-in for BinArchive: .extract(entry, oodle_dll) looks up canned bytes."""

    def __init__(self):
        self._payloads: dict[object, bytes] = {}

    def extract(self, entry, oodle_dll) -> bytes:
        return self._payloads[entry]


def _make_index(paths_and_bytes: dict[str, bytes]) -> PackIndex:
    idx = PackIndex.__new__(PackIndex)
    idx.oodle_dll = "unused"
    idx._by_hash = {}
    arc = _FakeArchive()
    for path, payload in paths_and_bytes.items():
        entry = object()  # opaque sentinel; only identity matters
        arc._payloads[entry] = payload
        idx._by_hash[file_hash(path)] = (arc, entry)
    return idx


def test_has_true_for_present_path():
    idx = _make_index({"a/b.core": b"AB"})
    assert idx.has("a/b.core") is True


def test_has_false_for_missing_path():
    idx = _make_index({"a/b.core": b"AB"})
    assert idx.has("a/missing.core") is False


def test_has_core_delegates_to_has():
    idx = _make_index({"a/b.core": b"AB"})
    assert idx.has_core("a/b") is True
    assert idx.has_core("a/missing") is False


def test_read_by_hash_returns_bytes():
    idx = _make_index({"a/b.core": b"payload-bytes"})
    h = file_hash("a/b.core")
    assert idx.read_by_hash(h) == b"payload-bytes"


def test_read_by_hash_missing_raises_keyerror():
    idx = _make_index({"a/b.core": b"AB"})
    with pytest.raises(KeyError):
        idx.read_by_hash(0xDEADBEEF)


def test_read_and_read_by_hash_agree():
    idx = _make_index({"a/b.core": b"payload-bytes"})
    assert idx.read("a/b.core") == idx.read_by_hash(file_hash("a/b.core"))
