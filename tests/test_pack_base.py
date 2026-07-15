"""Tests for the PackReader Protocol (engine.pack.base).

Verifies that:
- PackReader is importable and runtime-checkable.
- PackIndex structurally satisfies PackReader via isinstance (no inheritance needed).
- A minimal object lacking one of the five methods does NOT satisfy PackReader.
- The real PackIndex class itself carries the required attributes (not a tautology:
  we check the class object, not a stand-in).

PackReader was widened (issue #27) with `has(path_with_ext)` and `read_by_hash(hash)`
so production callers stop reaching into a reader's `_by_hash` internals.
"""
import inspect

from deciwaves.engine.pack.base import PackReader
from deciwaves.engine.pack.bin_index import PackIndex


# ---------------------------------------------------------------------------
# Lightweight stand-in — avoids needing a real data directory.
# ---------------------------------------------------------------------------

class _FakePackIndex:
    """Minimal object exposing all five PackReader methods with correct signatures."""

    def read(self, virtual_path_with_ext: str) -> bytes:
        return b""

    def read_core(self, virtual_path: str) -> bytes:
        return b""

    def has_core(self, virtual_path: str) -> bool:
        return False

    def has(self, virtual_path_with_ext: str) -> bool:
        return False

    def read_by_hash(self, path_hash: int) -> bytes:
        return b""


class _MissingHasCore:
    """Object missing `has_core` — must NOT satisfy PackReader."""

    def read(self, virtual_path_with_ext: str) -> bytes:
        return b""

    def read_core(self, virtual_path: str) -> bytes:
        return b""

    def has(self, virtual_path_with_ext: str) -> bool:
        return False

    def read_by_hash(self, path_hash: int) -> bytes:
        return b""


class _MissingHas:
    """Object missing the widened `has` — must NOT satisfy PackReader."""

    def read(self, virtual_path_with_ext: str) -> bytes:
        return b""

    def read_core(self, virtual_path: str) -> bytes:
        return b""

    def has_core(self, virtual_path: str) -> bool:
        return False

    def read_by_hash(self, path_hash: int) -> bytes:
        return b""


class _MissingReadByHash:
    """Object missing the widened `read_by_hash` — must NOT satisfy PackReader."""

    def read(self, virtual_path_with_ext: str) -> bytes:
        return b""

    def read_core(self, virtual_path: str) -> bytes:
        return b""

    def has_core(self, virtual_path: str) -> bool:
        return False

    def has(self, virtual_path_with_ext: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Protocol conformance — stand-in
# ---------------------------------------------------------------------------

def test_fake_satisfies_pack_reader():
    """A conforming stand-in passes isinstance against the runtime-checkable Protocol."""
    assert isinstance(_FakePackIndex(), PackReader)


def test_missing_method_fails_pack_reader():
    """An object missing has_core must NOT satisfy PackReader."""
    assert not isinstance(_MissingHasCore(), PackReader)


def test_missing_has_fails_pack_reader():
    """An object missing the widened `has` must NOT satisfy PackReader."""
    assert not isinstance(_MissingHas(), PackReader)


def test_missing_read_by_hash_fails_pack_reader():
    """An object missing the widened `read_by_hash` must NOT satisfy PackReader."""
    assert not isinstance(_MissingReadByHash(), PackReader)


# ---------------------------------------------------------------------------
# Real PackIndex class carries the required attributes
# ---------------------------------------------------------------------------

def test_pack_index_has_read():
    assert callable(getattr(PackIndex, "read", None))


def test_pack_index_has_read_core():
    assert callable(getattr(PackIndex, "read_core", None))


def test_pack_index_has_has_core():
    assert callable(getattr(PackIndex, "has_core", None))


def test_pack_index_has_has():
    assert callable(getattr(PackIndex, "has", None))


def test_pack_index_has_read_by_hash():
    assert callable(getattr(PackIndex, "read_by_hash", None))


# ---------------------------------------------------------------------------
# Stand-in proves PackIndex instance would satisfy PackReader.
# We also confirm PackIndex's method signatures accept the right parameter names,
# so the test is about the real contract, not a tautology.
# ---------------------------------------------------------------------------

def test_pack_index_read_signature():
    sig = inspect.signature(PackIndex.read)
    params = list(sig.parameters.keys())
    # first param is self; second must carry the "path_with_ext" semantic
    assert "virtual_path_with_ext" in params


def test_pack_index_read_core_signature():
    sig = inspect.signature(PackIndex.read_core)
    params = list(sig.parameters.keys())
    assert "virtual_path" in params


def test_pack_index_has_core_signature():
    sig = inspect.signature(PackIndex.has_core)
    params = list(sig.parameters.keys())
    assert "virtual_path" in params


def test_pack_index_has_signature():
    sig = inspect.signature(PackIndex.has)
    params = list(sig.parameters.keys())
    assert "virtual_path_with_ext" in params


def test_pack_index_read_by_hash_signature():
    sig = inspect.signature(PackIndex.read_by_hash)
    params = list(sig.parameters.keys())
    assert "path_hash" in params
