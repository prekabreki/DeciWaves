---
description: DS2 dialogue audio is Wwise .wem (RIFF fmt 0xFFFF) inside DSAR containers that the repo's existing FwStreamStore reads unmodified, and DS2 ships parseable SentenceResource/LocalizedTextResource -- but its 12-locator block is NOT FW's 12 languages
type: reference
---

Measured 2026-08-01 against the retail DS2 install, on top of the graph layout in
[[ds2-streaming-graph]]. This is the Phase 2/3 gate for `docs/ds2-support-spec.md`:
codec, subtitle source, and line count.

## The codec is Wwise `.wem`, not FW's ATRAC9

Read at the real per-line locator addresses (not sniffed from a filename):

    RIFF/WAVE | fmt tag 0xFFFF | ch=1 | rate=48000 | chunks: fmt(66) hash(16) data

`0xFFFF` is Wwise's vendor codec id; 3,000/3,000 sampled clips agree. FW is plain
RIFF/ATRAC9 decoded with **VGAudio** — DS2 is not. DS2 belongs with DS1 and HZD on the
**vgmstream** path (see [[ds-wwise-wem-format]]). So the FW *container* work transfers and
the FW *decoder* choice does not; do not wire DS2 to `VGAudioCli`.

## The existing DSAR reader already resolves DS2 audio, unmodified

`package.01.00.core.stream` and its per-language siblings are **DSAR** containers, so
locator offsets are DSAR-*logical*, not physical file offsets. Reading the raw file at a
locator offset yields high-entropy compressed bytes and looks like a broken parse — that is
the expected symptom, not a desync.

`engine.pack.fw_stream.FwStreamStore` sniffs `DSAR` per file and already handles this:
15/15 sampled locators across root, `l200_aus` and `l100_mex` returned valid clips with no
code change. **DS2 Phase 2 needs no new container reader and no new locator arithmetic.**

Verification invariant, byte-exact and independent of the parse that produced it:

    next_locator_in_block - locator == RIFF size field + 8   (the clip's total length)

Confirmed on root (10,560) and `l200_aus` (33,544). Use this as Phase 2's oracle — it is far
stronger than "the clip started with RIFF".

A refuted hypothesis, recorded so it is not retried: physical clip starts are **not** a
constant delta from logical offsets. Sweeping one delta over the file matched 1 of 11,112
locators, with 9,090 distinct nearest-RIFF deltas. Only leading, uncompressed DSAR blocks
happen to line up, which makes a small sample look convincing.

## DS2 ships parseable sentence/text resources — the DS1-style path, not ASR

Object counts from the graph type table (`type_hash(name)` membership, no object walk):

| type | objects |
| --- | --- |
| `LocalizedTextResource` | 27,474 |
| `SentenceResource` | 19,760 |
| `LocalizedSimpleSoundResource` | 16,921 |
| `WwiseWemResource` | 7,838 |
| `SentenceGroupResource` | 2,505 |
| `WwiseWemLocalizedResource` | 536 |
| `VoiceResource` | 118 |
| `WwiseBankResource` | 74 |

FW and HZD needed ASR against a BYO gamescript because subtitle text was not reachable.
DS2 looks like DS1 instead: subtitles and speaker plausibly derivable from resources. This
is the single biggest scope difference for Phase 3 — it may remove the GPU ASR stage
entirely, so scope Phase 3 to *try the resource path first*.

Nuance on [[ds2-streaming-graph]]'s 23%-shared-type-hash caveat: only 9 of 26 guessed type
names resolve, and 4,753 of 4,762 DS2 type hashes stay unnamed — but every dialogue-relevant
name above hashes **identically** in both games. The type *names and ids* for what we care
about did carry over; what is unproven is each compound's field *layout*.

## The real Phase 3 blocker is a DS2 type database

`fw_rtti.TypeRegistry` deserialises objects field-by-field from odradek's generated
`types.json`, which this repo **does not ship** — it is BYO via `--types-json` / `--fw-types`
and is FW-specific. Reading a DS2 `SentenceResource` needs a DS2 `types.json`. Decima
Workshop v0.1.27 ("Odradek") targets HFW and DS2 as one lineage
([[decima-workshop-wrong-for-death-stranding-1]]), so generating one is plausible — but it is
a prerequisite, not a detail, and it is where Phase 3 will stall if unaddressed.

## The `lNNN_*` directories are CONTENT partitions, not languages

This corrects the natural reading of the directory names, and it is the single easiest way to
mis-scope DS2. The seven `lNNN_*` dirs look like locale codes (`l800_fra` especially) and are
not. Verified by decoding 3 of the longest clips from each directory with `vgmstream-cli` and
running language ID over all 21: **every clip is English** (p = 0.69–1.00, mostly > 0.95), with
coherent in-game dialogue. The `l` prefix reads as *level*:

| dir | content |
| --- | --- |
| `l100_mex` | Mexico region (Villa Libre, Wokka) |
| `l200_aus` | Australia region (emu, koala) |
| `l400_nr1` / `l500_nr2` / `l600_nr3` | companion/assistant hint lines |
| `l700_bea` | Beach / plot-critical material |
| `root` | base game + lore (the Mary Shelley / Kojima Productions easter egg) |

So on an English-only install **all of it is English**, and English is *not* identifiable by a
path segment the way FW's `en/` is. `fw_fast_extract._EN_STREAM_RE` has no DS2 equivalent and
must not be ported; DS2's English selection is "every stream", filtered by content partition
if anything.

Width-12 arith-clean blocks by directory (all English):

    root 3,359 | l200_aus 4,671 | l100_mex 659 | l700_bea 39
    l400_nr1 23 | l600_nr3 13 | l500_nr2 12

Of 16,921 LSSRs, 8,776 sit in width-12 arith-clean groups (758 clean groups, 33 with a
non-integer locator ratio); other widths are rare (24: 16, 16: 4, 13: 2).

## FW's stride-12 slot-0 indexing does yield the right line

All twelve slots of a block point at the *same* file (identical per-slot file distribution
across all 8,776 blocks), so the block is not twelve languages in this install. But
`locators[locator_start + 12*k]` still resolves the k-th LSSR to its own distinct clip:
decoding k = 34, 35, 37 of group 2176 returned three **sequential narrative lines**. So the
arithmetic of `fw_fast_extract.iter_english_lines` transfers; only its English-detection
regex does not.

Unknown, and irrelevant to English-first scope: what slots 1–11 would address in a
multi-language install. Do not assume they are language slots just because FW's are.

## 99 of 241 indexed files are absent from disk — expected, not a broken install

The `Files` table indexes `package.NN.MM` slots per content partition; only some exist. The
absent slots carry locator counts *identical* to the present ones per partition (root 11,112,
`l200_aus` 5,081, `l100_mex` 717 …), i.e. they address the same logical content, not missing
audio. 78 files also have a max locator offset exceeding their physical size — again
logical-space addressing, consistent with DSAR. Any DS2 stage must tolerate absent file
indices rather than treating them as corruption.

## Decoder provisioning was already solved — do not rebuild it

`vgmstream-cli` is already a pinned, registered tool that `deciwaves setup` installs, so DS2
being Wwise means it needs **no new tooling** — it reuses that entry and specifically not
`VGAudioCli`. Do not vendor a binary or add a download path for it. The two traps that make a
configured machine look like it has no decoder (runtime-set env vars; the `.venv`
`%LOCALAPPDATA%` virtualization) are in [[decoder-tool-resolution]].

The real DS2 gap is the reverse direction: there is no `ds2_package` config key, no
`setup --ds2-package`, and no doctor DS2 line — issue #355, per `docs/ds2-support-spec.md`.
