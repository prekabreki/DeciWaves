# Death Stranding 2 support — design spec

Status: approved 2026-08-01. Phase 0 done; the Phase 2/3 gate is measured (see
[`.memories/ds2-audio-binding.md`]) and Phase 1 is dispatched as #353.

DS2 (`DEATH STRANDING 2: ON THE BEACH`) becomes the fourth game in the
`GameProfile` seam. This spec fixes the architectural bet and the epic's shape;
it deliberately leaves Phases 2–5 unscoped, because a single unresolved binary
format gates every downstream estimate.

## The bet: DS2 is the Forbidden West generation, not DS1's

Despite the name, `games/ds/` is the wrong starting point. DS2 ships
`LocalCacheWinGame/package/` with `package.NN.MM.core` + `.core.stream` pairs,
per-language subdirectories, and a root `HashDB.bin` — the FW layout, not DS1's
`data/*.bin` and not HZD Remastered's format. Community tooling agrees: Decima
Workshop v0.1.27 ("Odradek") targets HFW and DS2 as one lineage, which is
exactly why it chokes on DS:DC (see
[`.memories/decima-workshop-wrong-for-death-stranding-1.md`]).

### What is proven

Verified directly against the retail install on 2026-08-01:

| Fact | Evidence |
| --- | --- |
| DS2 ships a `streaming_graph.core` | `LocalCacheWinGame/package/streaming_graph.core`, 28,332,251 bytes |
| It is the same resource type as FW's | Leading `u64` type hash is `0x929d7af6a30cd1c5` — byte-identical to FW's `StreamingGraphResource` |
| The header layout is shared through `SpanTable` | Fields step cleanly with plausible counts; DS2's `LinkTableSize` (30,226,923) is the *exact* on-disk size of its `streaming_links.stream`, an independent confirmation of sync |
| The body diverges at `Groups`/`SubGroups` | See table below |
| `HashDB.bin` is not a DS2 novelty | FW ships one too; `grep -rin hashdb src/ tests/ docs/ .memories/` returns nothing, and FW works without it |

Field counts read by stepping the FW layout over both files:

| Field | FW | DS2 |
| --- | --- | --- |
| TypeHashes | 3,266 | 4,762 |
| LinkTableSize | 99,139,565 | 30,226,923 |
| LocatorTable | 1,384,347 | 369,397 |
| ArrayTable | 1,801,913 | 896,760 |
| SpanTable | 126,824 | 79,317 |
| Groups | 103,826 | 79,317 |
| **SubGroups** | 1,387,648 | **0** |
| **RootUUIDs / RootIndices** | 37,548 / 37,548 | **45,847 / 70,322** |
| **Files** | 127 | **16,395 (garbage)** |

`engine.pack.fw_streaming_graph.StreamingGraph` therefore raises on DS2's graph.
The most likely cause is that `StreamingGroupData` is no longer 64 bytes, or a
field was inserted around it; `Files` decoding to garbage is a downstream symptom
of that desync, not a separate problem.

**This is a bounded delta to a reader we already own and understand — not a
fourth distinct binding approach.** That is the single most important finding
behind this spec.

### What was unknown — now measured (2026-08-01)

Answers in [`.memories/ds2-audio-binding.md`]; summarised here because they
change Phases 2–5:

- **The audio codec is Wwise `.wem`** (RIFF/WAVE, `fmt` tag `0xFFFF`, mono
  48 kHz), read at real locator addresses — *not* FW's ATRAC9. DS2 decodes on the
  **vgmstream** path with DS1 and HZD, not with VGAudio.
- **The audio streams are DSAR containers**, so locator offsets are logical, and
  `engine.pack.fw_stream.FwStreamStore` already resolves them **unmodified**
  (15/15 sampled clips). Phase 2 needs no new container or locator work.
- **DS2 does ship parseable sentence/subtitle resources** — 19,760
  `SentenceResource`, 27,474 `LocalizedTextResource`, 2,505 `SentenceGroupResource`.
  This is the DS1-style path, so Phase 3 should try resource-derived
  subtitles/speaker *before* reaching for ASR, which may drop the GPU stage entirely.
- **Line count:** 16,921 `LocalizedSimpleSoundResource`, 8,776 of them in
  arithmetically clean width-12 groups.
- **The `lNNN_*` directories are content partitions, not languages.**
  Decoding 3 clips from each and running language ID returns **English for every
  one** — `l100_mex` is the Mexico region, `l200_aus` Australia, `l700_bea` the
  Beach, `l400_nr1`/`l500_nr2`/`l600_nr3` companion hint lines, `root` base +
  lore. `fw_fast_extract._EN_STREAM_RE` (which keys on an `en/` path segment) has
  no DS2 equivalent and must not be ported.
  **`l800_fra` hosts zero dialogue** (0 of 8,776 blocks) — it holds ~800 MB of
  multichannel music/ambience, so it is out of scope for voice rather than
  "English". It was not covered by the original language-ID sample; see
  [`.memories/ds2-audio-binding.md`].
- **FW's stride-12 arithmetic transfers, and the 12 slots really are 12
  languages** (corrected 2026-08-01, second pass). Slot 0's file is present on
  disk for 8,776/8,776 blocks and slots 1–11 for 0/8,776, so
  `locators[locator_start + 12*k]` slot 0 is the installed language *by
  construction*. All 8,769 readable slot-0 clips are mono Wwise; 10/10 transcribe
  as English DS2 dialogue. `english_file_indices` should be **replaced** by an
  on-disk filter (7 stream files), not deleted.
- **Phase 2's oracle is per-file adjacency, not within-block adjacency.**
  `next_offset - offset >= riff_size + 8` holds for 8,709/8,709 adjacent slot-0
  pairs in the same file (zero overlaps), exact for 98.34%. The
  `next_locator_in_block` form named in an earlier draft fails 7,574 of 8,032 and
  must not be used as a test.
- **Phase 3's real prerequisite is a DS2 `types.json`.** `fw_rtti` deserialises
  objects from odradek's generated type database, which this repo does not ship
  (BYO, FW-specific). Reading a DS2 `SentenceResource` needs a DS2 one.

Decoder provisioning needs **no new work**: `vgmstream-cli` is already pinned in
`cli.config.TOOLS`, installed by `deciwaves setup` into `tools_dir`, reported by
`doctor`, and wired by `config.apply_tool_env`. DS2 being Wwise means it uses that
existing tool rather than `VGAudioCli`. The DS2 side of that wiring is **done** (#355,
merged): a `ds2_package` config key, `setup --ds2-package`, and a `check_ds2_package`
doctor line. Note the naming: the flag/key is `--ds2-package` / `ds2_package` (the
`...\LocalCacheWinGame\package` dir), mirroring FW's `--fw-package`, while the env var
`DECIWAVES_DS2_INSTALL` is the *install root*, mirroring `DECIWAVES_FW_INSTALL`. An
earlier draft of this spec said `ds2_install` / `--ds2-install`; that was never built.

## Architecture

A new `src/deciwaves/games/ds2/` package. `engine/pack/fw_streaming_graph.py`
gains **variant detection** and remains the single reader for both games —
justified because the header is provably identical for a large prefix of the
body. `games/ds/` (DS1) is untouched despite the name collision.

Also required: a `DECIWAVES_DS2_INSTALL` environment variable following the
existing convention, a `deciwaves ds2 <stage>` CLI chain, and `deciwaves doctor`
integration.

**Guard rail:** anything DS2 needs that FW's reader cannot express as a variant
branch is a signal to fork the module, not to contort it. Per `CLAUDE.md`, true
cross-game agnosticism is a non-goal; the shared seam earns its keep only for
what is genuinely common.

## Epic shape: spike-gated

```
Phase 0  RE the graph variant            IN-SESSION  → .memories/ds2-streaming-graph.md
Phase 1  reader variant + fixtures       foreman, ready once Phase 0 lands
Phase 2  extract → WAV + manifest CSV    scoped after Phase 1  (needs: codec)
Phase 3  speaker / subtitle binding      scoped after Phase 1  (needs: sentence-resource answer)
Phase 4  story order                     scoped after Phase 3  (needs: BYO gamescript decision)
Phase 5  render → ≤290 MB MP3 reels      scoped after Phase 4
```

Only Phase 1 receives a full acceptance-criteria issue at epic creation. Phases
2–5 exist as titled placeholders and are scoped for real once Phase 0 reports
the codec, the subtitle source, and the line count. Writing them now would be
fiction.

### Why Phase 0 is not executor work

Binary-format reverse engineering has no ground truth an executor can check
itself against: a wrong-but-size-exact parse looks green, and the
`chase-the-executors-excuse` failure mode applies directly. Phase 0 is done
in-session against the real install and written up as
`.memories/ds2-streaming-graph.md` (field table, strides, deltas vs FW).

That memory then becomes the specification for Phase 1, which *is* good executor
work — closed-form, with a real oracle:

- the parser's existing size-exact assertion (`c.pos != body_end`), and
- `Files[]` decoding as UTF-8 `cache:package/...` paths, matching FW's shape.

## Testing

Follows the established pattern exactly, with no new invention:

- `tests/test_fixtures_ds2_streaming_graph.py` hand-builds synthetic bytes and
  runs the **real, unmodified** parser over them — mirroring
  `tests/test_fixtures_fw_streaming_graph.py`.
- Install-gated tests `pytest.skip` without `DECIWAVES_DS2_INSTALL`, mirroring
  the `fw_streaming_graph_bytes` fixture in `tests/conftest.py`.
- No 28 MB `.core` blob enters git. Per `CLAUDE.md`, extracted audio and
  install-derived data stay out of the repo.

The suite stays green on a clean machine with only the base install.

## Stated assumptions

Both are cheap to revisit, and are recorded here rather than left implicit:

1. **English-only first**, matching FW's scope. The other six language
   directories are deferred, not designed out.
2. **The epic's definition of done is the repo's standard per-game DoD** — a
   manifest CSV of voice lines with stable IDs, speaker, category/scene,
   language and playable WAV paths, rendered into ≤290 MB story-ordered MP3
   reels. Not a reduced one.

## Provenance

DS2 ownership confirmed by the user on 2026-08-01 (PSN pre-order receipt,
Digital Deluxe Edition). The repo's bring-your-own-game constraint holds: this
epic ships code that reads an install the user owns, never game content.
