import json

from deciwaves.engine.pack.fw_rtti import TypeRegistry


def _write_types_json(tmp_path, types):
    p = tmp_path / "types.json"
    p.write_text(json.dumps(types), encoding="utf-8")
    return str(p)


def _simple_types():
    return {
        "Simple": {
            "kind": "compound",
            "bases": [],
            "attrs": [
                {"name": "b", "type": "int32", "offset": 4, "flags": 0},
                {"name": "a", "type": "int32", "offset": 0, "flags": 0},
            ],
        }
    }


def test_ordered_attrs_sorts_by_offset(tmp_path):
    reg = TypeRegistry(_write_types_json(tmp_path, _simple_types()))
    assert reg.ordered_attrs("Simple") == (("a", "int32"), ("b", "int32"))


def test_ordered_attrs_caches_per_instance_not_globally(tmp_path):
    """ordered_attrs must be cached per-TypeRegistry instance, not via
    functools.lru_cache keyed on self -- which would pin every instance (and
    its loaded types.json dict) alive for the process lifetime. Two separate
    instances must have independent caches."""
    path = _write_types_json(tmp_path, _simple_types())
    reg_a = TypeRegistry(path)
    reg_b = TypeRegistry(path)

    result_a = reg_a.ordered_attrs("Simple")
    result_b = reg_b.ordered_attrs("Simple")
    assert result_a == result_b

    # Each instance owns its own cache dict -- clearing one must not disturb
    # the other's already-cached entry.
    assert "Simple" in reg_a._ordered_attrs_cache
    assert "Simple" in reg_b._ordered_attrs_cache
    reg_a._ordered_attrs_cache.clear()
    assert "Simple" not in reg_a._ordered_attrs_cache
    assert "Simple" in reg_b._ordered_attrs_cache  # untouched
    # reg_a still works correctly after its cache was cleared (recomputes)
    assert reg_a.ordered_attrs("Simple") == result_a


def test_ordered_attrs_drops_dont_serialize_binary_flag(tmp_path):
    types = {
        "WithFlag": {
            "kind": "compound",
            "bases": [],
            "attrs": [
                {"name": "kept", "type": "int32", "offset": 0, "flags": 0},
                {"name": "dropped", "type": "int32", "offset": 4, "flags": 2},
            ],
        }
    }
    reg = TypeRegistry(_write_types_json(tmp_path, types))
    assert reg.ordered_attrs("WithFlag") == (("kept", "int32"),)
