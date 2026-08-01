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

## The 12-locator block is NOT twelve languages

FW's fast path relies on 12 locators per LSSR = 12 dubbed languages with **English at block
offset 0** (`fw_fast_extract.iter_english_lines`). DS2 has the same width-12 shape and it
means something else: across all 8,776 width-12 blocks, **all twelve slots point at the same
file**, with an identical per-slot file distribution. Language is therefore a property of the
whole block, and copying FW's "offset 0 is English" gives silent nonsense — it reads
whichever language that block belongs to.

Width-12 arith-clean blocks by directory:

    (root) 3,359 | l200_aus 4,671 | l100_mex 659 | l700_bea 39
    l400_nr1 23 | l600_nr3 13 | l500_nr2 12

Of 16,921 LSSRs, 8,776 sit in width-12 arith-clean groups (758 clean groups, 33 with a
non-integer locator ratio); other widths are rare (24: 16, 16: 4, 13: 2).

**Open question, cheap to close:** which directory is English. Phase 0 concluded root, and
root is much the largest stream (592 MB vs `l200_aus` 256 MB), which is consistent — but
`l200_aus` holds *more* width-12 blocks, so it is not proven. Decode one clip from each and
listen. Blocked right now only because **no Wwise decoder is installed on this machine** —
`DECIWAVES_VGMSTREAM` is unset and no `vgmstream-cli` is on PATH or in a tools dir.

## 99 of 241 indexed files are absent from disk — expected, not a broken install

The `Files` table indexes `package.NN.MM` slots per language; only some exist. The absent
slots carry locator counts *identical* to the present ones per language (root 11,112,
`l200_aus` 5,081, `l100_mex` 717 …), i.e. they are patch/variant slots addressing the same
logical content, not missing audio. 78 files also have a max locator offset exceeding their
physical size — again logical-space addressing, consistent with DSAR. Any DS2 stage must
tolerate absent file indices rather than treating them as corruption.
