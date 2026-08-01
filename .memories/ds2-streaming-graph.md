---
description: Death Stranding 2's streaming_graph.core is Forbidden West's StreamingGraphResource with exactly two layout deltas -- a 68-byte group stride and a trailing GGUUID array -- but only 23% of its RTTI type hashes are shared with FW
type: reference
---

Death Stranding 2 is the **Forbidden West generation**, not DS1's (see
[[decima-workshop-wrong-for-death-stranding-1]]). It ships
`LocalCacheWinGame/package/streaming_graph.core` carrying the *same* resource type as FW:

    u64 type_hash == 0x929d7af6a30cd1c5   # murmur3_x64_128(seed=42, "00000001_StreamingGraphResource").low64

Byte-identical to FW's, despite the `00000001_` type-db version prefix that would notionally
have tracked a layout change. **The version prefix did not bump even though the layout did** —
so the type hash alone is not sufficient to decide whether FW's reader applies.

Measured 2026-08-01 against the retail installs of both games. Both parse size-exact.

## The two deltas vs [[fw-streaming-graph]]

**1. `StreamingGroupData` is 68 bytes, not 64.** FW's fifteen fields map 1:1 onto DS2's first
64 bytes; DS2 appends one trailing `u32` at offset @64 that is **zero in every one of the
79,317 retail records**. Purpose unknown — treat it as reserved, not as a field to interpret.

**2. A trailing `Array<GGUUID(16)>` after `PackFileMaxCompressedBlockSize`.** 444 entries in
retail, `4 + 444*16 = 7,108` bytes. FW's body ends at the block sizes; DS2's does not.
Without this the parse falls exactly 7,108 bytes short.

Everything else is unchanged, including the `Filename` framing (`u32 length, u32 crc32,
byte[length]`, UTF-8, not NUL-terminated) and the `Span` / `ObjectLocator` strides.

`PackFileUncompressedBlockSize` / `PackFileMaxCompressedBlockSize` read `(0, 0)` — **in both
games**. That is normal, not a DS2 anomaly, and not evidence of a desync.

## How the stride was pinned (the technique, not just the answer)

Stepping the FW layout blindly over DS2 desyncs at `Groups` and produces plausible-looking
garbage (`SubGroups=0`, `RootUUIDs=45,847 != RootIndices=70,322`, `Files=16,395`). Guessing
from there is unfalsifiable. What worked instead was **anchoring on a known-shape landmark and
solving by arithmetic**:

1. `Files[]` must contain literal ASCII `cache:package/`. A raw byte search found 241
   occurrences; backing up 8 bytes revealed intact `u32 len, u32 crc` framing, and 4 more
   revealed the array count — pinning `Files[]` at absolute offset 26,858,527, count 241.
2. The gap between end-of-`SpanTable` and that offset is 8,619,040 bytes, which must hold
   `Groups + SubGroups + RootUUIDs + RootIndices`. Sweeping the group stride, **only 68 lands
   exactly** — and it simultaneously restores FW's `RootUUIDs == RootIndices` invariant
   (50,513 = 50,513), which is independent of the arithmetic that produced it.
3. Field *identity* within the 68 bytes was then confirmed by reading the table as 17 `u32`
   columns and matching column sums against already-known array lengths, rather than by
   assuming FW's order held. Every column landed:

   | col @off | field | confirming invariant |
   | --- | --- | --- |
   | 0 @0 | `group_id` | sum = Σ1..79,317 exactly |
   | 1 @4, 11 @44 | `num_objects`, `type_count` | identical sums (5,353,645) |
   | 2-3 @8 | `group_size` (i8) | ~65 GB total |
   | 5 @20 | `sub_group_count` | Σ = 553,802 = SubGroups len |
   | 7 @28 | `root_count` | Σ = 50,513 = RootUUIDs len |
   | 9 @36 | `span_count` | Σ = 79,317 = SpanTable len |
   | 13 @52 | `link_size` | **Σ = 30,226,923 = exact byte size of `streaming_links.stream`** |
   | 15 @60 | `locator_count` | Σ = 369,397 = LocatorTable len |
   | 16 @64 | *(new)* | all zeros |

The `link_size` result is the strongest single check in the set: an on-disk file size,
reproduced by summing a column of a struct whose stride was derived independently.

**Generalisable lesson:** for a Decima layout delta, find an ASCII or size landmark, solve the
unknown stride as the only value that lands on it, then verify field identity by column sums
against known table lengths. A size-exact parse alone is weak evidence — it can be reached
with fields misassigned.

## Retail shape (DS2, for sanity-checking a reader)

    locators 369,397 | spans 79,317 | groups 79,317 | subgroups 553,802
    roots 50,513/50,513 | files 241 | packfiles 241/241 | objloc 45,345 | trailing uuids 444

`Files[]` distribution: 47 root-level (the base package — **English is here; DS2 ships no `en`
subdir**, unlike FW), 18 `remain/`, and seven language dirs (`l100_mex` 36, `l200_aus` 44,
`l400_nr1` 19, `l500_nr2` 19, `l600_nr3` 21, `l700_bea` 20, `l800_fra` 17).

## The caveat that matters for everything downstream

**Only 1,097 of DS2's 4,762 type hashes are shared with FW's 3,266** — 23% of DS2, 34% of FW.
The graph *container* transfers almost exactly; the RTTI type system underneath it did not.
Do not assume `fw_object_reader` / `fw_rtti` carry over at the object level, and do not assume
DS2's audio codec matches FW's RIFF/ATRAC9 (DS1 and HZD are Wwise `.wem`) until it is measured.
The cheap container win does not license optimism about the objects inside it.

`HashDB.bin` is **not** a DS2 novelty — FW ships one too, and no code in this repo references
either. It is a name-resolution convenience, not a prerequisite.

See [[fw-streaming-graph]] for the base layout this diffs against, and
`docs/ds2-support-spec.md` for the epic this unblocks.
