---
description: DS2 dialogue audio is Wwise .wem (RIFF fmt 0xFFFF, mono) inside DSAR containers that the repo's existing FwStreamStore reads unmodified; its 12-locator block IS FW's 12 languages with only slot 0 installed, and DS2 ships parseable SentenceResource/LocalizedTextResource
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

### Phase 2's oracle — CORRECTED 2026-08-01 (second pass)

An earlier version of this file stated the invariant as
`next_locator_in_block - locator == RIFF size field + 8`. **That is wrong and must not be
used as a test.** Measured over all 8,776 slot-0 dialogue locators it passes 458 and fails
7,574 — because consecutive locators *within* a block are twelve different languages in
twelve different files (see the corrected slot section below), so their offsets have no size
relation at all.

The invariant that does hold is per-file adjacency of the slot-0 clips:

    for slot-0 locators of ONE file, sorted by offset:
        next_offset - offset == RIFF size field + 8      # 8,564 of 8,709 pairs = 98.34%
        next_offset - offset >= RIFF size field + 8      # 8,709 of 8,709 = 100%, ZERO overlaps

The 145 inexact pairs are always *positive gaps* (max 84,968,898 bytes) where non-dialogue
assets sit between two runs of dialogue — never overlaps, so the weak form is a true
invariant and the strong form is a 98% statistical property. **Assert the no-overlap form;
measure the exact-adjacency rate, don't assert it.**

Stronger and simpler checks that are exactly true, and are the ones a Phase 2 test should use:

| check | measured |
| --- | --- |
| slot-0 locators total | 8,776 |
| start with `RIFF` | 8,769 (99.92%) |
| `fmt` tag `0xFFFF` (Wwise) | 8,769 / 8,769 |
| channels == 1 (mono) | 8,769 / 8,769 |
| distinct stream files holding dialogue | **7** |

Exactly **7 slot-0 locators do not start with `RIFF`** and must be tolerated, not treated as
corruption — `(file_index, offset)` = (40, 141988345), (39, 116945984), (39, 135705080),
(39, 146512470), (39, 229474561), (38, 33516875), (38, 33996916). A further **60 offsets are
duplicated** (two LSSRs sharing one clip — reused lines), so a manifest keyed on
`(file_index, offset)` would silently lose rows; key it on the line id.

Content confirmed by transcription of 10 slot-0 clips (faster-whisper medium, GPU): all
English at p = 0.95–0.99, all recognisably DS2 — "Later, Sammy!", "There's a patch of BT
territory due north of here", "we focus on monitoring the behavior of tar currents".

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

**Measured 2026-08-01: the FW `types.json` on this machine cannot be reused for DS2.** Hashing
all 12,173 of its named types and intersecting against each game's graph type table:

| game | distinct graph type hashes | named by the FW `types.json` |
| --- | --- | --- |
| FW | 2,367 | **2,367 (100.0%)** |
| DS2 | 3,677 | **792 (21.5%)** |

So it is definitively FW's database (100% coverage is not a coincidence), and it leaves 2,885 of
DS2's graph types unnamed. It also contains **none** of `WwiseWemResource`,
`WwiseWemLocalizedResource` or `WwiseBankResource` — precisely the DS2 audio resource types —
while it does carry `SentenceResource`, `SentenceGroupResource`, `LocalizedTextResource`,
`LocalizedSimpleSoundResource` and `VoiceResource`. Those five names hash identically in both
games, but a shared name does not imply a shared field *layout*, so even they are unproven for
DS2. Phase 3 needs a DS2-generated `types.json`; do not try to point `--types-json` at this file.

Machine note: it lives at `\\192.168.50.250\NAS10TB\deciwaves-e2e\types.json` and is the
configured `fw_types` value.

## The `lNNN_*` directories are CONTENT partitions, not languages

This corrects the natural reading of the directory names, and it is the single easiest way to
mis-scope DS2. The `lNNN_*` dirs look like locale codes (`l800_fra` especially) and are not.
Verified by decoding 3 of the longest clips from each directory with `vgmstream-cli` and
running language ID over all 21: **every clip is English** (p = 0.69–1.00, mostly > 0.95), with
coherent in-game dialogue.

⚠ **Scope of that check, corrected 2026-08-01 (second pass).** It covered six `lNNN_*` dirs
plus `root` — **not** `l800_fra`, the one dir whose name most suggests a language. The table
below lists `root` in the seventh position, which disguised the gap. `l800_fra` was then
checked directly and the conclusion survives, for a better reason than "it is English":

- **`l800_fra` contains zero dialogue.** Of the 744 arith-clean width-12 LSSR groups, **none**
  addresses an `l800_fra` file (0 of 8,776 blocks). It is not a voice source at all.
- It does hold ~800 MB of Wwise audio across 6 present files (`package.40.00.core.stream` alone
  is 368 MB), but sampling it off the stride-12 path yields **6-channel and 2-channel** clips,
  while every dialogue clip in this game is **mono**. faster-whisper returns empty
  transcriptions and its classic non-speech hallucinations ("THE END", "Thank you for your
  viewing") on them — i.e. music/ambience beds, not voice.
- So English-first scope is safe, and `l800_fra` is *out of scope for dialogue* rather than
  *English*. Whether `fra` denotes French assets or a level name is still unknown and no longer
  blocks anything.

The `l` prefix reads as *level*:

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

Width-12 arith-clean blocks by directory (all English; reproduced exactly on the second pass
with the repo's own `arith_clean_lssr_count`, so these seven numbers are solid):

    l200_aus 4,671 | root 3,359 | l100_mex 659 | l700_bea 39
    l400_nr1 23 | l600_nr3 13 | l500_nr2 12 | l800_fra 0     (total 8,776)

Group-classification counts differ slightly between passes — 744 arith-clean + 47
non-integer-ratio (second pass) vs 758 + 33 (first). The total 791 and the block total 8,776
agree exactly, so the disagreement is in how borderline groups are bucketed, not in the
dialogue set. Prefer the block counts above; treat the group split as approximate.

Of 16,921 LSSRs, 8,776 sit in width-12 arith-clean groups (758 clean groups, 33 with a
non-integer locator ratio); other widths are rare (24: 16, 16: 4, 13: 2).

## The 12 slots ARE 12 languages — DS2 is FW's layout exactly

**Corrected 2026-08-01 (second pass).** An earlier version of this file said "all twelve slots
of a block point at the *same* file … so the block is not twelve languages in this install",
and warned "do not assume they are language slots just because FW's are". Both statements are
wrong, and the truth is the more convenient one.

Expanding one block slot-by-slot shows twelve *different* files, in strict ascending order:

    slot  0  file[ 40] package.01.00.core.stream   offset 5,592,160   on disk: YES
    slot  1  file[ 49] package.02.00.core.stream   offset 5,901,512   on disk: no
    slot  2  file[ 54] package.03.00.core.stream   offset 5,916,783   on disk: no
    ...                                                              (slots 3-11 all absent)

Per-slot distinct `file_index` sets over 200 blocks are disjoint and monotone
(slot 0 ∈ {39,40}, slot 1 ∈ {49,50}, slot 2 ∈ {53,54} … slot 11 ∈ {136,137}). So slot index is
a real, separate dimension from the block index.

What the earlier pass almost certainly compared was the per-slot **partition** distribution,
which *is* identical across slots (every slot shows the same `l200_aus` 4,671 / `root` 3,359 /
`l100_mex` 659 / … split) — because each language ships the same content partitions. Identical
partition histograms, twelve different files.

Consequences, all favourable:

- `LANGS = 12` in `fw_fast_extract` is semantically correct for DS2, not a coincidence.
- `locators[locator_start + 12*k]` slot 0 is the installed language **by construction**, and
  independently confirmed: 100% on-disk, 8,769/8,776 valid mono Wwise RIFF, 10/10 transcribed
  as English DS2 dialogue.
- The earlier framing "DS2's English selection is *every stream*" is too loose — it is *slot 0
  of every dialogue block*, which happens to span 7 stream files.

### `iter_english_lines` needs NO changes at all — verified

`fw_fast_extract.iter_english_lines(graph, en_indices)` already takes the accepted stream-file
index set as a parameter, so the *only* DS2-specific piece is computing that set. Passing "every
file index present on disk" reproduces the measurement exactly:

```python
on_disk = {i for i, f in enumerate(graph.files)
           if os.path.isfile(os.path.join(package_dir, strip_cache_prefix(f)))}
lines = list(iter_english_lines(graph, on_disk))     # -> exactly 8,776
```

    files on disk: 142 of 241
    FastLines yielded: 8,776          # independent census also said 8,776
    distinct stream files used: 7     # {40:3359, 39:4671, 42:659, 38:39, 41:23, 36:13, 34:12}
    line_id unique: True (8,776)

So DS2 Phase 2 needs **no new container reader, no new locator arithmetic, and no new
resolver** — just an on-disk index helper (~4 lines), a stage that mirrors `games/fw/extract.py`
with `vgmstream-cli` in place of `VGAudioCli`, and CLI wiring. Note `english_file_indices`
raises `KeyError` on an empty set, so the helper must fail loudly on a wrong package dir rather
than yielding zero lines silently.

## 99 of 241 indexed files are absent from disk — because they are the OTHER 11 LANGUAGES

**Corrected 2026-08-01 (second pass).** An earlier version of this file called the absent
slots "patch/variant slots addressing the same logical content". They are not: they are the
non-installed languages. The per-slot on-disk census makes it unambiguous — of the 8,776
dialogue blocks, slot 0's file is present **8,776/8,776 (100%)** and every one of slots 1–11
is present **0/8,776 (0%)**. That is a language dimension, not a patch dimension, and it is
exactly FW's layout.

The earlier reading was right that absent file indices must be tolerated rather than treated
as corruption — but the reason matters, because it is what makes slot 0 the correct and
*principled* choice rather than a lucky one (see below).

## Decoder provisioning was already solved — do not rebuild it

`vgmstream-cli` is already a pinned, registered tool that `deciwaves setup` installs, so DS2
being Wwise means it needs **no new tooling** — it reuses that entry and specifically not
`VGAudioCli`. Do not vendor a binary or add a download path for it. The two traps that make a
configured machine look like it has no decoder (runtime-set env vars; the `.venv`
`%LOCALAPPDATA%` virtualization) are in [[decoder-tool-resolution]].

The reverse-direction gap (no `ds2_package` config key, no `setup --ds2-package`, no doctor
DS2 line) was **closed by #355**, merged 2026-08-01. `ds2_package` is a persisted config key,
`deciwaves setup --ds2-package` records it and warns if pointed at the install root, and
`doctor.check_ds2_package` reports the usual three states keyed on `streaming_graph.core`.
Verified against the retail install at merge time: unset → `NOT_CONFIGURED`, install root →
`BROKEN` with a hint naming the corrected path, real package dir → `OK`, and `doctor`'s exit
code is byte-identical to pre-#355 on a machine with no config file.
