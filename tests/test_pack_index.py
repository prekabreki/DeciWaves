# tests/test_pack_index.py
import pytest

from deciwaves.engine.pack.base import PackReader
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


def test_pack_index_satisfies_pack_reader():
    """`GameProfile.pack_reader` is typed `PackReader` but the repo runs no type
    checker, so the annotation alone is checked by nothing (issue #337). This is the
    runtime conformance check for DS's reader, mirroring
    `test_hzd_package.py::test_hzd_package_satisfies_pack_reader` -- drop any of
    read/read_core/has/read_by_hash from PackIndex and this goes red.

    Uses the hermetic fake index: `isinstance` against a @runtime_checkable Protocol
    tests the class's methods, so no real install or Oodle DLL is needed."""
    assert isinstance(_make_index({}), PackReader)


def test_has_true_for_present_path():
    idx = _make_index({"a/b.core": b"AB"})
    assert idx.has("a/b.core") is True


def test_has_false_for_missing_path():
    idx = _make_index({"a/b.core": b"AB"})
    assert idx.has("a/missing.core") is False


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


# ---------------------------------------------------------------------------
# Empty-data-dir construction (issue #414): a data_dir with no .bin archives must
# fail fast and name the directory, instead of silently building an empty index
# that later blames every individual stream.
# ---------------------------------------------------------------------------

def test_empty_data_dir_raises_naming_the_dir(tmp_path):
    empty_dir = tmp_path / "install_root"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError) as exc_info:
        PackIndex(str(empty_dir), "unused")
    # Substring, not ``match=``: a Windows path is not a valid regex.
    assert str(empty_dir) in str(exc_info.value)


def test_data_dir_with_unrelated_files_still_raises(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "readme.txt").write_text("not an archive")
    with pytest.raises(FileNotFoundError):
        PackIndex(str(data_dir), "unused")


def test_data_dir_with_one_bin_does_not_raise_on_empty_check(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "archive.bin").write_bytes(b"not a real archive, just needs to exist")
    # A real (unparseable) .bin still fails, but on archive parsing, not the empty-dir guard.
    with pytest.raises(Exception) as exc_info:
        PackIndex(str(data_dir), "unused")
    assert "no .bin archives found" not in str(exc_info.value)
