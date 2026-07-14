"""Deserialise the objects of one Forbidden West streaming group and resolve
each line's audio locator by positional pairing.

Ported from odradek's ``StreamingObjectReader``: a group allocates one object
per entry in its type table, then its span bytes are read sequentially, filling
each object as a compound. Every *valid* ``StreamingDataSource``
(``Channel != 0xFF and Length > 0``) consumes the next entry from the group's
locator slice — that pairing is the line -> audio binding.

We read only the group's own objects (its locator slice is consumed solely by
them; subgroups have their own slices), and we do NOT resolve cross-object
pointers — for audio extraction a pointer is just a ``u8 present`` byte in the
span (plus an inline 16-byte GGUUID for ``UUIDRef``); the link table that
resolves pointer *targets* lives in separate bytes and is not needed here.

Per-object size-exactness is asserted against each span, which catches any
type-layout error immediately (the same discipline as the ``.core`` walk).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from deciwaves.engine.pack.fw_rtti import TypeRegistry
from deciwaves.engine.pack.fw_streaming_graph import Group, StreamingGraph
from deciwaves.engine.pack.fw_stream import FwStreamStore

# Number of written (subtitle) languages in HFW = English + 11 dubbed + 14
# subtitle-only (odradek ELanguageExtension; English is index 0, lowest value).
_WRITTEN_LANGUAGES = 26

# Types whose on-disk form carries extra binary after the declared attrs
# (MsgReadBinary / ExtraBinaryDataHolder). Only those reachable in dialogue
# groups are handled; an unhandled one raises so coverage gaps are explicit.
_EXTRA_BINARY = {"LocalizedTextResource"}

_PRIMITIVE_SIZES = {
    "bool": 1, "wchar": 2, "tchar": 2, "uint8": 1, "int8": 1,
    "uint16": 2, "int16": 2, "uint": 4, "int": 4, "uint32": 4, "int32": 4,
    "ucs4": 4, "uint64": 8, "int64": 8, "uintptr": 8, "intptr": 8,
    "HalfFloat": 2, "float": 4, "double": 8, "uint128": 16,
}
_INT_FMT = {1: "<b", 2: "<h", 4: "<i", 8: "<q", 16: None}


@dataclass
class FwObject:
    type_name: str
    fields: dict = field(default_factory=dict)


class _Cur:
    __slots__ = ("d", "p", "end")

    def __init__(self, d: bytes, start: int, end: int):
        self.d, self.p, self.end = d, start, end

    def take(self, n: int) -> bytes:
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def u8(self) -> int:
        v = self.d[self.p]
        self.p += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v


class GroupReader:
    def __init__(self, graph: StreamingGraph, registry: TypeRegistry):
        self.graph = graph
        self.reg = registry

    def read_group(self, group: Group, span_blobs: list[bytes]) -> list[FwObject]:
        """Deserialise *group*'s objects. *span_blobs* are the raw bytes of each
        of the group's spans (caller reads them so this stays I/O-free)."""
        type_names = [
            self.reg.name_for_hash(int(h))
            for h in self.graph.type_table[group.type_start:group.type_start + group.type_count]
        ]
        objects = [FwObject(tn) for tn in type_names]
        # locator cursor: consumed by every valid StreamingDataSource (including
        # ones nested inside the LSSR's LocalizedDataSources array), in order.
        self._locators = iter(
            self.graph.locators[group.locator_start:group.locator_start + group.locator_count]
        )

        index = 0
        assert len(span_blobs) == group.span_count
        for blob in span_blobs:
            cur = _Cur(blob, 0, len(blob))
            while cur.p < cur.end:
                obj = objects[index]
                index += 1
                self._fill_compound(obj.type_name, cur, obj.fields)
            if cur.p != cur.end:
                raise ValueError(
                    f"span not size-exact in group {group.group_id}: "
                    f"{cur.p} != {cur.end}"
                )
        if index != len(objects):
            raise ValueError(
                f"group {group.group_id}: filled {index} of {len(objects)} objects"
            )
        return objects

    @staticmethod
    def _sds_valid(fields: dict) -> bool:
        return fields.get("Channel", 0xFF) != 0xFF and fields.get("Length", 0) > 0

    # --- lean scan: keep the locator cursor exact but only materialise LSSRs --
    def scan_group(self, group: Group, span_blobs: list[bytes],
                   capture=("LocalizedSimpleSoundResource", "LocalizedTextResource")) -> list[FwObject]:
        """Like :meth:`read_group` but skips dict-building for objects whose type
        is not in *capture*. Every object is still walked (so nested
        ``StreamingDataSource`` locators are consumed in the right order); only
        captured objects are returned. Essential for the giant groups (up to
        ~96k objects) where full materialisation is impractical."""
        type_names = [
            self.reg.name_for_hash(int(h))
            for h in self.graph.type_table[group.type_start:group.type_start + group.type_count]
        ]
        self._locators = iter(
            self.graph.locators[group.locator_start:group.locator_start + group.locator_count]
        )
        captured: list[FwObject] = []
        index = 0
        assert len(span_blobs) == group.span_count
        for blob in span_blobs:
            cur = _Cur(blob, 0, len(blob))
            while cur.p < cur.end:
                tn = type_names[index]
                index += 1
                if tn in capture:
                    obj = FwObject(tn)
                    self._fill_compound(tn, cur, obj.fields)
                    captured.append(obj)
                else:
                    self._advance(tn, cur)
            if cur.p != cur.end:
                raise ValueError(
                    f"span not size-exact in group {group.group_id}: {cur.p} != {cur.end}"
                )
        return captured

    def _advance(self, type_name: str, cur: _Cur) -> None:
        """Advance *cur* past one value of *type_name* without building objects,
        but still consume a locator for every valid StreamingDataSource."""
        reg = self.reg
        kind = reg.kind(type_name)
        if kind == "atom":
            self._advance_atom(type_name, cur)
        elif kind in ("enum", "enum flags"):
            cur.p += reg.define(type_name)["size"]
        elif kind == "pointer":
            if cur.u8() and reg.define(type_name)["type"] == "UUIDRef":
                cur.p += 16  # inline GGUUID
        elif kind == "container":
            self._advance_container(type_name, cur)
        elif kind == "compound":
            if type_name == "StreamingDataSource" or type_name in _EXTRA_BINARY:
                fields: dict = {}
                self._fill_compound(type_name, cur, fields)  # SDS locator / extra-binary
            else:
                for _n, t in reg.ordered_attrs(type_name):
                    self._advance(t, cur)
        else:
            raise NotImplementedError(f"kind {kind} ({type_name})")

    def _advance_atom(self, type_name: str, cur: _Cur) -> None:
        reg = self.reg
        name = type_name
        while reg.kind(name) == "atom":
            bt = reg.define(name)["base_type"]
            if bt == name:
                break
            name = bt
        if name in ("String", "Filename"):
            self._read_string(cur)
        elif name == "WString":
            cur.p += cur.u32() * 2
        else:
            cur.p += _PRIMITIVE_SIZES[name]

    @staticmethod
    def _check_count(count: int, cur: _Cur) -> None:
        """Reject an implausible container count: every item consumes at least
        one byte, so a count larger than the bytes remaining in the span means
        the walk has desynced. Raise (caught fail-soft) rather than loop billions
        of times on a misread u32 (seen as the g61935 hang)."""
        if count > cur.end - cur.p:
            raise ValueError(f"implausible container count {count} "
                             f"(> {cur.end - cur.p} bytes left) -> walk desync")

    def _advance_container(self, type_name: str, cur: _Cur) -> None:
        d = self.reg.define(type_name)
        ctype, item = d["type"], d["item_type"]
        count = cur.u32()
        self._check_count(count, cur)
        if ctype not in ("HashMap", "HashSet"):
            nm = item
            while self.reg.kind(nm) == "atom":
                bt = self.reg.define(nm)["base_type"]
                if bt == nm:
                    break
                nm = bt
            if nm in _PRIMITIVE_SIZES and nm not in ("String", "Filename", "WString"):
                cur.p += count * _PRIMITIVE_SIZES[nm]
                return
        for _ in range(count):
            if ctype in ("HashMap", "HashSet"):
                cur.p += 4  # per-entry hash
            self._advance(item, cur)

    # --- type-driven reader -------------------------------------------------
    def _fill_compound(self, type_name: str, cur: _Cur, out: dict) -> None:
        for attr_name, attr_type in self.reg.ordered_attrs(type_name):
            out[attr_name] = self._read(attr_type, cur)
        # mirror odradek's overridden fillCompound: any StreamingDataSource
        # (nested or top-level) consumes a locator when valid.
        if type_name == "StreamingDataSource" and self._sds_valid(out):
            out["_locator"] = next(self._locators)
        elif type_name in _EXTRA_BINARY:
            out["_texts"] = self._read_extra_binary(type_name, cur)

    def _read_extra_binary(self, type_name: str, cur: _Cur):
        """Read the MsgReadBinary trailer for *type_name* (ExtraBinaryDataHolder)."""
        if type_name == "LocalizedTextResource":
            # 26 written languages: each u16 length + that many UTF-8 bytes
            # (no crc, unlike the String atom). English = index 0.
            texts = []
            for _ in range(_WRITTEN_LANGUAGES):
                ln = struct.unpack_from("<H", cur.d, cur.p)[0]
                cur.p += 2
                texts.append(cur.take(ln).decode("utf-8", "replace"))
            return texts
        raise NotImplementedError(f"extra-binary type {type_name}")

    def _read(self, type_name: str, cur: _Cur):
        reg = self.reg
        kind = reg.kind(type_name)
        if kind == "atom":
            return self._read_atom(type_name, cur)
        if kind in ("enum", "enum flags"):
            return self._read_int(reg.define(type_name)["size"], cur)
        if kind == "compound":
            sub: dict = {}
            self._fill_compound(type_name, cur, sub)
            return sub
        if kind == "pointer":
            return self._read_pointer(type_name, cur)
        if kind == "container":
            return self._read_container(type_name, cur)
        raise NotImplementedError(f"kind {kind} ({type_name})")

    def _read_atom(self, type_name: str, cur: _Cur):
        # resolve atom base_type chain to a primitive
        reg = self.reg
        name = type_name
        seen = set()
        while reg.kind(name) == "atom":
            bt = reg.define(name)["base_type"]
            if bt == name or bt in seen:  # builtin self-ref (e.g. HalfFloat)
                break
            seen.add(name)
            name = bt
        if name in ("String", "Filename"):
            return self._read_string(cur)
        if name == "WString":
            length = cur.u32()
            return cur.take(length * 2).decode("utf-16-le") if length else ""
        size = _PRIMITIVE_SIZES[name]
        raw = cur.take(size)
        if name == "float":
            return struct.unpack("<f", raw)[0]
        if name == "double":
            return struct.unpack("<d", raw)[0]
        if name == "HalfFloat":
            return struct.unpack("<e", raw)[0]
        return int.from_bytes(raw, "little", signed=name[0] == "i")

    @staticmethod
    def _read_int(size: int, cur: _Cur) -> int:
        return int.from_bytes(cur.take(size), "little")

    @staticmethod
    def _read_string(cur: _Cur) -> str:
        length = cur.u32()
        if length == 0:
            return ""
        cur.u32()  # crc32
        return cur.take(length).decode("utf-8", "replace")

    def _read_pointer(self, type_name: str, cur: _Cur):
        present = cur.u8()
        if not present:
            return None
        ptype = self.reg.define(type_name)["type"]
        if ptype == "UUIDRef":
            return self._read("GGUUID", cur)  # inline 16-byte uuid
        return "<link>"  # non-UUIDRef: target lives in the (unread) link table

    def _read_container(self, type_name: str, cur: _Cur):
        d = self.reg.define(type_name)
        ctype, item = d["type"], d["item_type"]
        count = cur.u32()
        self._check_count(count, cur)
        is_hash = ctype in ("HashMap", "HashSet")
        # fast path for byte arrays
        if not is_hash and self.reg.kind(item) == "atom":
            ar = self.reg
            nm = item
            while ar.kind(nm) == "atom":
                bt = ar.define(nm)["base_type"]
                if bt == nm:
                    break
                nm = bt
            if nm in _PRIMITIVE_SIZES and nm not in ("String", "Filename", "WString"):
                return cur.take(count * _PRIMITIVE_SIZES[nm])
        out = []
        for _ in range(count):
            if is_hash:
                cur.u32()  # per-entry hash
            out.append(self._read(item, cur))
        return out


def read_group_spans(graph: StreamingGraph, store: FwStreamStore, group: Group) -> list[bytes]:
    """Read each of *group*'s span byte ranges from the package store."""
    blobs = []
    for sp in graph.spans[group.span_start:group.span_start + group.span_count]:
        blobs.append(store.read(sp.file_index, sp.offset, sp.length))
    return blobs
