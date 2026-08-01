---
description: A DS2 types.json with 100% graph-type coverage exists (odradek ships one, same source as the FW file already in use) -- but it does NOT unblock Phase 3 on its own, because GroupReader fails on 100% of DS2 dialogue groups while succeeding on FW
type: reference
---

Measured 2026-08-01, closing out the research half of issue #362. Supersedes the assumption in
that issue that "generate a DS2 types.json" was the whole Phase 3 blocker. Background:
[[ds2-audio-binding]], [[ds2-streaming-graph]].

## The types.json half is SOLVED

The tool `docs/BYO.md` names ("odradek") is **its own repo**, `ShadelessFox/odradek` (GPL-3.0) --
*not* Decima Workshop / `ShadelessFox/decima`, which is the older lineage. Issue #362 and
[[decima-workshop-wrong-for-death-stranding-1]] conflate the two. Odradek targets HFW **and DS2**
and ships a generated type database per game as a build resource:

    odradek-game-ds2/src/main/resources/types.json   8,640,176 bytes
    odradek-game-hfw/src/main/resources/types.json   3,990,566 bytes

**Nothing needed generating.** The FW `types.json` this project already depends on is
*semantically identical* to odradek's HFW resource -- 12,173 types, **100% identical definitions**,
differing only in whitespace. So using odradek's DS2 resource is the same provenance as the FW
file, not a new decision.

Coverage, measured with the same check that produced the 21.5% figure (hashing every named type
with `fw_rtti.type_hash` against `graph.type_table`):

| types.json | DS2 graph types | named |
| --- | --- | --- |
| FW (the old one) | 3,677 | 792 (21.5%) |
| **odradek DS2** | 3,677 | **3,677 (100.0%)** |

All eight dialogue/audio types resolve, including the three the FW file lacked entirely:
`SentenceResource`, `SentenceGroupResource`, `LocalizedTextResource`,
`LocalizedSimpleSoundResource`, `VoiceResource`, `WwiseWemResource`,
`WwiseWemLocalizedResource`, `WwiseBankResource`.

`TypeRegistry` loads it without modification (20,106 types registered). The sibling
`types_name_collision_fix.patch` only rewrites `{"category": "Event"}` markers, which the loader
**ignores** (`docs/BYO.md`: an `attrs` entry with no `name` is a category marker) -- irrelevant here.

Saved locally at `\\192.168.50.250\NAS10TB\deciwaves-e2e\types-ds2.json`, beside the FW one.
Still BYO: never commit it.

## But it does NOT unblock Phase 3

With that database loaded, `fw_object_reader.GroupReader.scan_group` fails on **1,378 of 1,378**
DS2 groups containing a `LocalizedTextResource` -- buffer underruns and container-count desyncs
while walking fields (`unpack_from requires a buffer of at least N bytes`).

This is **not** a bad type database and **not** a broken harness. The identical script, pointed at
the FW install with the FW types.json as a control, parses **262 of 402** groups and returns
readable strings ("Gold Ingot", "tenakth_adult_male1"). The failure is DS2-specific.

So DS2's *object/group serialization* differs from FW's, exactly as its `StreamingGraph` did
(see [[ds2-streaming-graph]]'s two layout deltas). **Phase 3 needs a DS2 variant of the object
reader, and that RE work -- not the type database -- is the real remaining blocker.** Scope it
the way Phase 0 was scoped: in-session research, not executor work.
