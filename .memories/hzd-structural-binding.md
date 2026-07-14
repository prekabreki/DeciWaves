---
description: HZD's per-line audio binding uses a structural content fingerprint (encoded byte length + decoded sample count) to bucket clips against catalog lines, falling back to a small, targeted ASR pass only for buckets with more than one candidate
type: reference
---

## Identity is fully readable per line; the sound resource is not self-naming

Unlike Death Stranding, HZD's sentence resources are flat — no group wrapper, just a
repeating triple of (sentence, sound, text) resources per line — and the speaker is a
readable path segment (a human-readable name) rather than a coded id. The English subtitle
sits at a fixed language-slot index inside the text resource. So a line's identity (speaker,
subtitle, internal name) is fully recoverable directly from the resource tree.

What is *not* directly recoverable is which physical audio clip belongs to which line: HZD's
sound resource has no literal per-line stream path the way DS's does (see
[[ds-wwise-wem-format]]) — only an inline per-language data block with no addressable stream
key. And unlike Forbidden West (see [[fw-streaming-graph]]), HZD Remastered ships no
positional ordering index that would let the binding be replayed by walking resources in
engine order. The direct stream key is a build-time value with no on-disk derivation path —
a dead end for exact resolution, which is why a content-based approach was needed instead of a
lookup.

## The structural fingerprint join

Each line's inline sound-resource data block yields two cheap, no-decode fingerprint values:

- **A** — the encoded clip's byte length (matches the archive entry's byte length exactly).
- **B** — the decoded sample count (readable from the codec's header without a full decode).

Computing (A, B) for every candidate clip and for every catalog line, then grouping by the
(A, B) pair, collapses the vast majority of naive same-length collisions into a single unique
clip-per-line bucket — these bind for free, with no ASR needed. Only buckets with more than
one candidate clip need disambiguation.

## ASR only for the leftover collisions

For a multi-candidate bucket, a fuzzy text match between each candidate's transcribed audio
(via ASR) and the known subtitle text of each candidate line picks the right pairing. Because
the bucket is already narrowed to a handful of candidates sharing an exact (A, B)
fingerprint, this ASR pass only has to run over the small collision set, not the whole corpus
— the structural join does the heavy lifting.

**A real false-match found by ear:** a naive "are these two texts similar" scorer that ignores
word order can return a perfect score when a short line's words all happen to appear, in any
order, somewhere inside a much longer transcript — silently mis-binding a short line into an
unrelated longer one even though the text "matched". The fix is to fall back to an
order-sensitive comparison whenever one candidate is much shorter than the other, rather than
trusting a subset-tolerant score across a large length gap. Lesson: a text-similarity score can
be perfect and still be the wrong clip — listening to the rendered result catches binding
errors a text-only precision sample misses.

## A known, accepted gap

A small fraction of lines carry no inline (A, B) fingerprint at all and are simply left
unbound — roughly half of that residual are genuinely unvoiced bracketed stage-direction
subtitles (no audio ever existed for them), and the rest are real dialogue behind a stub or
missing sound resource that would need a separate reference-following step to recover. This is
treated as a known property of the source data, not a bug in the binding pipeline.
