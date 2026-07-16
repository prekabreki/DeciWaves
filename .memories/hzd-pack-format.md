---
description: HZD Remastered ships the newer Forbidden-West-generation package format (unencrypted DSAR archives + a path-hash index), not DS's encrypted packfile — a different reader is required
type: reference
---

Horizon Zero Dawn *Remastered* was rebuilt on the newer Decima engine generation, so it does
**not** use the older encrypted packfile format that Death Stranding uses. It uses the same
family of packaging Forbidden West uses: a set of `package.NN.NN.core[.stream]` archive files
plus a separate index file mapping path hashes to (archive, offset, length). A reader built for
DS's encrypted format will not read HZD Remastered at all — a distinct reader over the index
file is required, and it turned out to double as groundwork for the Forbidden West reader later.

## Archive container (DSAR), little-endian

Both `.core` and `.core.stream` files share one chunked container format: a small fixed header
(magic + version + chunk count + offset to the first chunk + total logical size), followed by
one fixed-size descriptor per chunk (logical offset, physical offset, uncompressed size,
compressed size, codec tag). Two things simplify this format relative to the older encrypted
packfile:

- **No encryption.** The chunk table and chunk bytes are plain — no XOR/key-schedule step.
- **LZ4 block compression, not Oodle/Kraken.** The only codec tag this format uses is LZ4
  block; the Oodle/Kraken material belongs entirely to the older encrypted-packfile format.

Reading a logical byte range means: find the chunk whose logical offset is the greatest one
at-or-below the target position, seek to its physical offset, LZ4-decompress its compressed
span, and slice within it (a read spanning a chunk boundary continues into the next chunk).

## Index file layout

The index is a flat list of named packfile groups, each holding its own list of file records:
`(path_hash: u64, offset: u32, length: u32)`. A record's archive is implicit from which
packfile group it appears under — there's no per-record archive field. Both `.core` (resource)
entries and `.core.stream` (streamed payload, e.g. audio) entries live in the same kind of
table, addressed the same way.

**The path hash reuses the exact same primitive** as the older encrypted-packfile format:
MurmurHash3 x64-128, seed 42, first 64 bits, over the NUL-terminated UTF-8 virtual path (with
backslashes normalized to forward slashes). One hashing routine, shared by both games' readers.

**Retail index files carry a short trailing section after the last packfile group** (observed
2026-07-16, issue #46: 39 bytes decoding as `u8 0x01`, then `u32 name_len=18`,
`"ShaderBinaries.bin"`, `u64 hash`, `u32 offset=0`, `u32 length=0xFFFFFFFF` — likely a
count-prefixed loose-file list, but that reading is n=1 empirical). A byte-exact parse
precondition on this file is therefore wrong on real installs; the reader warns about
unconsumed trailing bytes instead of raising, while truncation mid-record still fails hard.

## Resource type hashes are a fresh empirical problem per engine generation

Decima RTTI type hashes are derived from a type's field layout, which changes across engine
generations — so hashes discovered for one game's resource types do not carry over to
another. HZD Remastered's resource-format hashes turned out to match the Forbidden-West-era
engine (consistent with being a from-scratch rebuild), not the original 2017 release, so they
had to be rediscovered empirically rather than assumed from any published older-game hash
table. The type hash itself is derivable, though: it equals the low 64 bits of
MurmurHash3 x64-128 (seed 42) of the bare type name string, which lets an unknown observed hash
be confirmed or an expected type's hash be predicted, without needing an external oracle for
every type.

See [[hzd-structural-binding]] for how per-line audio is bound once the pack and resource
layers are readable.
