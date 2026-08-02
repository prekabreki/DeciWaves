---
description: Forbidden West ships a positional streaming-graph index that HZD Remastered lacks, so its per-line audio binding is resolved by replaying deserialization order rather than by content fingerprinting
type: reference
---

The structural difference that makes Forbidden West's audio binding tractable where HZD
Remastered's isn't (see [[hzd-structural-binding]]) is a single large resource: a
streaming-graph index that records, globally, the archive each streamed payload lives in and
a table of locator entries (each encoding an archive index plus a byte offset). HZD
Remastered ships no equivalent file — its binding had to be solved by content fingerprinting
instead, because there is no ordering authority to replay.

## Positional pairing, not a key lookup

The index does not map a line to its locator by any stored key. Instead, resolving a line's
audio means **replaying deserialization order**: walking a dialogue group's resources in the
same order the engine would construct them, and consuming the next locator table entry for
every valid inline data source encountered along the way. A dialogue line's sound resource
holds one inline data source per spoken language (English is conventionally the lowest-valued
language slot in the list), so within a group, resolving English means consuming the correct
one of several per-language locator slots per line, in walk order.

Two independent inline fields on the resource — the encoded clip's byte length and the
decoded sample count — both matching the values found at the locator-resolved location serves
as a strong correctness cross-check that the positional replay landed on the right entry.

## A fast path for well-behaved groups

Full positional replay requires a general reader for every resource type that can appear in a
dialogue group, including several large embedded types (animation curves, textures, and
similar) that aren't dialogue-relevant themselves but still occupy a slot in the walk order and
will desync the locator cursor if skipped incorrectly. For groups where the total locator count
divides evenly by the number of per-language slots, though, the k-th line's target-language
clip can be found by pure arithmetic — no walk needed, no exposure to the unhandled-type
problem. This fast path covers a large majority of lines cheaply; the remainder need the full
walk (and, for the ones with unsupported embedded types, are skipped fail-soft rather than
aborting the run).

### MEASURED 2026-08-02 (#399): "the remainder" is 35.8% of the game, and nothing walks it

"A large majority" is 64.2%, and the remainder is not handled anywhere:

| | count |
| --- | --- |
| `LocalizedSimpleSoundResource` objects in the type table | 95,392 |
| reached by the fast path (1,498 arith-clean groups) | 61,217 (64.2%) |
| **in 437 non-clean groups — never extracted** | **34,175 (35.8%)** |

`games/fw/extract.py:152` is the only caller in FW's chain and it uses the fast path alone. The
comment at `engine/pack/fw_fast_extract.py:18` claiming the rest "need the full `GroupReader` walk
and are **handled elsewhere**" is **aspirational — do not believe it**. FW does use `GroupReader`,
but only inside `subtitle_bind` and only over `scan_arith_clean_groups`: the same clean groups. That
stage also fills WAV paths *from the clip-index*, so it can only annotate clips `extract` already
produced. **No stage in the FW chain can add audio the fast path skipped.**

This is the same defect [[ds2-audio-binding]] fixed for DS2 (#391), found by running DS2's
measurement against FW. **The DS2 fix does not port verbatim**: DS2 has exactly 7 language cycles,
one per region; FW shows **14 distinct 12-windows** across its clean groups, because a language is
split across `package.01.00` / `01.01` parts so a slot's file index varies by group. FW needs its
own alignment rule — measure the window population across *all* LSSR-bearing groups first, then
decide between an enumerated template set and a structural predicate. Tracked as **#399**.

Consequence for the deliverable: FW's rendered reels are missing roughly a third of the game's
voice lines, independently of [[deciwaves-reels-predate-output-fixes]]'s ordering staleness.

## Codec and read model

The resolved clip is a self-describing RIFF stream, ATRAC9-encoded (decoded via the same
ATRAC9 decoder used for HZD). Archive files may themselves be either raw or chunk-container
encoded (see [[hzd-pack-format]] for the chunk-container format shared across this engine
generation) — the reader has to sniff which applies per archive rather than assuming one.

See [[fw-subtitle-binding]] for how per-line labeling (as opposed to audio binding) is solved
on top of this same index.
