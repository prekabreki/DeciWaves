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

## Codec and read model

The resolved clip is a self-describing RIFF stream, ATRAC9-encoded (decoded via the same
ATRAC9 decoder used for HZD). Archive files may themselves be either raw or chunk-container
encoded (see [[hzd-pack-format]] for the chunk-container format shared across this engine
generation) — the reader has to sniff which applies per archive rather than assuming one.

See [[fw-subtitle-binding]] for how per-line labeling (as opposed to audio binding) is solved
on top of this same index.
