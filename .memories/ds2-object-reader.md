---
description: DS2's object serialization is FW's with exactly three deltas -- a 27-entry LocalizedTextResource trailer, a 3-byte per-entry suffix, and a new 8-byte StringHash atom -- taking GroupReader from 0/1378 to 803/1378 and yielding real exact subtitles
type: reference
---

Measured 2026-08-02 against the retail DS2 install, closing the research half of issue #370.
Background: [[ds2-types-json]] (which measured the 0/1,378 failure), [[ds2-streaming-graph]]
(the same "find the delta" exercise one layer up). The type database was never the problem —
odradek's DS2 `types.json` is 100% correct and loads unmodified.

## The three deltas vs FW's `fw_object_reader`

**1. `LocalizedTextResource` carries 27 language entries, not 26.** FW's `_WRITTEN_LANGUAGES = 26`
is derived from its `ELanguage` enum: 27 values minus the `Unknown` placeholder. DS2's `ELanguage`
has **28** values — the same list plus a trailing **`English_UK`** — so DS2 writes **27**. The count
is therefore *derivable from the loaded type database*, not a magic number: `len(ELanguage) - 1`.

**2. Each entry has a 3-byte trailer FW does not have.** The per-entry framing is
`u16 length, length UTF-8 bytes, 3 trailing bytes` (FW: no trailer). The third byte is a flag, not
padding — across 117k entries it is `00 00 00` 116,529 times and `00 00 01` 1,170 times. Purpose
unknown; treat as reserved. **This is the delta that actually caused the reported failure** — the
language count alone changes nothing, because the walk desyncs before the trailer is reached.

**3. `StringHash` is a new DS2-only builtin atom, 8 bytes.** DS2's type db defines it as a
self-referencing atom (`base_type == "StringHash"`) with no size, so `_resolve_atom` terminates on
it and `_PRIMITIVE_SIZES` raises `KeyError`. FW has **zero** unhandled terminal atoms; DS2 has two —
`StringHash` and `MotionMatchingVecN` (the latter never appears in dialogue groups; size unmeasured).

## How each value was pinned (the technique)

The decisive artifact was **group 76650: exactly one object, one span, 211 bytes** — the minimal
`LocalizedTextResource` in the game. Hand-decoding it solved the layout by arithmetic:

    16 (ObjectUUID GGUUID) + 27 entries x (2 len + 3 trailer) + sum(len)=60  ==  211 exactly

Then each parameter was swept independently against the corpus, and **each is uniquely correct** —
every neighbouring value collapses to 0%:

| parameter | 25 | 26 | **27** | 28 |
| --- | --- | --- | --- | --- |
| language count | 0% | 0% | **87.5%** | 0% |

| parameter | 0 | 1 | 2 | **3** | 4 |
| --- | --- | --- | --- | --- | --- |
| entry trailer bytes | 0% | 0% | 0% | **87.5%** | 0% |

`StringHash` is the one value not sharp — 2/4/16 all give 85.2% and **8 gives 89.2%** (n=400), so it
is pinned by *improvement*, not by uniqueness. Weaker evidence than the other two; revisit if a
residual failure class points at it.

Note the language count was **predicted from the `ELanguage` enum before it was tested**, and the
sweep independently agreed. Two unrelated confirmations, which is the bar
[[ds2-streaming-graph]] sets ("a size-exact parse alone is weak evidence").

## Measured result

| | before | after |
| --- | --- | --- |
| groups with `LocalizedTextResource` parsed | **0 / 1,378** | **803 / 1,378 (58.3%)** |
| dialogue groups (carrying an LSSR) parsed | 0 / 770 | **389 / 770 (50.5%)** |

The FW control is **262/402 = 65%**, so DS2 is now within the same band as the game the reader was
written for — a partial parse rate is normal here, not a DS2 defect.

**2,106 non-empty English strings recovered, 1,713 of them 5+ words.** They are unambiguously real
exact subtitles, not credits noise:

    "Tell me about this blood boomerang."
    "There's a patch of BT territory due north of here..."
    "Naturally, most people would have to rely on blood bags sourced from donors, but since you have DOOMS"
    "Thing is, the Brigands don't have a chiral printer at their base as far as we know."

## What is still unsolved

**49.5% of dialogue groups still fail**, so this is a large step, not the finish. Residual error
classes, in order of frequency: `IndexError: index out of range` (61), `unpack requires a buffer of
4 bytes` (11), then scattered implausible-container-count desyncs and one non-size-exact span
(g74313). These are *not* explained by the three deltas above and need their own pass — most likely
one or more further compound-layout differences, findable the same way (shrink to a minimal group,
hand-decode, sweep).

**Refuted, do not retry:** changing only the language count (26 -> 27 or 28) with FW's trailer-less
framing. It produces byte-identical failures at byte-identical offsets — the reader never reaches
the trailer, so the count is inert on its own.

## MEASURED: this does NOT improve matching. ASR was never the bottleneck.

An earlier draft of this file predicted exact subtitles would "remove the single largest source of
matching error". **That was wrong, and the head-to-head refutes it.** Same 1,997 clips, same
gamescript, same matcher and thresholds — the only variable is the text fed in:

| text source | bound | rate |
| --- | --- | --- |
| ASR transcript (today) | 1,127 / 1,997 | 56.4% |
| **exact in-game subtitle** | 1,151 / 1,997 | **57.6%** |

**+24 binds, +2.1% relative.** WhisperX transcripts are already good enough that the game's literal
text buys almost nothing. **Do not finish #370 expecting a bind-rate win.**

## What the exact text DID buy: a clean diagnosis of the real constraint

Because an exact subtitle *is* the line, a failure to bind is evidence about the **gamescript**, not
about transcription. Best achievable score of each of the 644 unbound exact subtitles against any
gamescript sentence:

| best score | meaning | count |
| --- | --- | --- |
| >=90 | in the script; the greedy matcher lost it | 44 (6.8%) |
| 80-89 | borderline, just under `accept=80` | 28 (4.3%) |
| **60-79** | **script paraphrases the line** | **511 (79.3%)** |
| <60 | genuinely absent from the script | 61 (9.5%) |

So the binding ceiling is the **fan gamescript being a paraphrase, not a transcript** — four fifths
of failures are a similar-but-not-equal script sentence sitting just below the accept threshold.
This also corrects the inference in [[deciwaves-active-workstream-ds2]] that ~102% word-count parity
implied the script covers the game: bulk parity did **not** mean line-for-line coverage.

Cheapest untested levers, in order: the `accept` threshold (511 lines sit in the 60-79 band), then
the 44 lines the greedy assignment lost. Neither needs this reader.

## Where this reader IS still worth finishing

- **Bark culling for deliverable 2** — a clip carrying no subtitle is a bark by construction, which
  is a principled filter the word-count heuristic only approximates.
- **Output quality** — exact text in the reel tracklist instead of an ASR paraphrase.
- **Speaker/scene names via the link table — the one path a gamescript can never cap.**

## The gamescript-free speaker path (confirmed reachable, not yet built)

No fan gamescript will ever contain every line the extractor can excavate, so *any* attribution
strategy routed through one is capped by definition. The game's own metadata is not. DS2's
`SentenceResource` carries the entire chain in its own attrs:

    SentenceResource - Text        -> Ref_LocalizedTextResource        (the subtitle)
                     - Voice       -> Ref_VoiceResource                (the SPEAKER)
                     - DisplayVoice-> Ref_VoiceResource                (displayed name)
                     - SimpleSound -> Ref_LocalizedSimpleSoundResource (the audio clip)

    VoiceResource    - NameResource-> Ref_LocalizedTextResource        (speaker name as text)
                     - Gender, HideSpeakerName
    SentenceGroupResource - Sentences -> Array_Ref_SentenceResource    (conversation order)

**The blocker is the link table, and it is tractable.** These are `Ref` pointers, not `UUIDRef`, so
they serialise as a bare `u8 present` byte and the target lives in the unimplemented link data —
`_read_pointer` currently returns the placeholder `"<link>"`. But the link data is on disk and
already accounted for: summing the graph's per-group `link_size` column gives **30,226,923 bytes,
exactly the size of `streaming_links.stream`**. Same class of exact-reconciliation invariant that
pinned the group stride in [[ds2-streaming-graph]], so the per-group slicing is already solved —
only the in-slice entry format is unknown.

This, not better subtitle text, is the path that would give speaker + scene for lines no gamescript
contains.

## `streaming_links.stream` entry format — SOLVED (structure), partially solved (external hop)

Measured 2026-08-02. Slicing was already free: `Group.link_start` / `Group.link_size` are parsed,
and the per-group sizes sum to the file byte-for-byte (30,226,923).

**One entry per *present* pointer, in walk order.** A pointer whose in-span `u8` is 0 consumes
nothing; every pointer whose byte is 1 consumes exactly one entry. (The in-span byte is strictly
boolean — measured max value 1 over 2,067 `Ref` pointers, so it is *not* itself an index.) Entries
are **LEB128 varints**, not fixed width — the `0x80` continuation bit shows up in large groups.

- **Internal target** (same group): a single varint = the target's **object index within the group**.
- **External target**: a two-byte form, first byte `0x40 + <subgroup index>`, then a second byte
  (`0x00` in every small case examined — presumably the object index inside that subgroup).

Verified on six independent groups; the walk order matches entry order exactly in all six:

    g1640   objs=[SR,SR,LTR(2),LTR(3)]      02 | 40 00 | 03 | 40 00
            walk: Text->obj2, Voice->ext, Text->obj3, Voice->ext        (4 present, 4 entries)
    g12490  objs=[SR,LSSR(1),LTR(2)]        01 | 02 | 42 00 | 40 00 | 41 00
            walk: SimpleSound->obj1, Text->obj2, Voice/Group/Preset->ext (5 present, 5 entries)
    g6769   objs=[SR,...,LSSR(5),LTR(6)]    05 | 06 | 41 00 | 40 00 | 42 00
    g2136   objs=[SR,...,LSSR(2),LTR(3)]    02 | 03 | 41 00 | 40 00 | 42 00
    g28891  objs=[SR,SR,LTR(2),LTR(3)]      02 | 40 00 | 03 | 41 00
    g15039  objs=[SR,LSSR(1)]               01 | 41 00 | 40 00 | 42 00

**The subgroup-index reading is corroborated independently** by `Group.sub_group_count`: g1640 has
1 subgroup and both externals read `40`; g28891 has 2 and reads `40`/`41`; g12490 and g15039 have 3
and read `40`/`41`/`42`. The external byte never exceeds `0x40 + sub_group_count - 1`.

**42,814 of 79,317 groups have `link_size == 0`** — no pointers at all, so any reader must treat an
empty slice as normal, not as a failure.

### Still unknown / do not assume

- **The internal/external discriminator does not generalise as a `< 0x40` threshold.** g48089 has
  103 objects, so its internal indices exceed 64 and would collide with the `0x40` external flag.
  Its slice contains multi-byte varints (`80 52`, `80 4e`, ...). The real encoding is therefore a
  varint with a flag bit, not a bare index — pin it on a large group before trusting any reader.
- The second byte of an external entry is `0x00` in every small case seen; unconfirmed on a group
  whose subgroup holds more than one referenced object.
- **Refuted:** "the slice holds only external refs as fixed-width `u16`s" — fits just 5.4% of
  groups, because internal refs are present too and the width is variable.
