---
description: Forbidden West's in-game subtitles are readable per group but not positionally paired to their audio clip — recovered via a bounded within-group fuzzy match against ASR instead of a global external-script match
type: reference
---

Forbidden West's dialogue groups carry a genuine in-game English subtitle resource (the same
text used for on-screen captions), readable per group the same way the audio locators are
readable (see [[fw-streaming-graph]]). This is a materially better label source than an
external fan transcript: it is exact, sourced from the game itself, and — critically — its
mere presence or absence is a strong dialogue-vs-bark filter, since ambient/combat barks
generally carry no subtitle at all. That "has a subtitle" signal recovers a large, clean,
story-grade subset of all extracted clips for free, without needing any external script.

## The naive assumption fails: subtitle order and audio order are independently shuffled

The tempting shortcut — "the k-th subtitle in a group belongs to the k-th audio clip in that
group" — is **false** for any group with more than one line. Within a single group, the
subtitle resource's internal walk order, the audio resource's internal walk order, and the
underlying dialogue line order are three separately-shuffled orderings. Even where a subtitle
and an audio entry sit at the same physical position in their respective walks, the *content*
pairing is frequently NOT a match — measured across a sample of multi-line groups, only a
minority landed on the identity permutation or its simple reverse; most were some other
shuffle entirely. Single-line groups are of course trivially exact, since there's nothing to
mis-pair, but they're a small minority of groups.

## Recovery: bounded local disambiguation, not global fuzzy matching

Within one group, the number of subtitles and the number of audio clips are both small and
equal (in the well-behaved case), so a **greedy one-to-one best-match assignment** between a
group's subtitles and its ASR-transcribed clips (using a fuzzy text similarity score) resolves
the pairing with very high accuracy. This is a fundamentally easier problem than matching
against an external script globally: the candidate set per line is a handful of in-group
options, not the entire corpus, so the ASR is only doing local disambiguation, not carrying the
whole labeling burden. The few low-confidence assignments that remain tend to be genuine ASR
transcription failures on hard audio (music bleed, noise, foreign-language mislabeling) rather
than mis-pairing.

## An external gamescript-style transcript is optional, not primary

Once subtitles are read directly, an external narrative-transcript source (if one is used at
all) only adds value as a *secondary* signal — matching each subtitle-labeled line's exact
text against such a transcript can recover speaker attribution and chronological/narrative
ordering for the subset of lines the transcript happens to cover, layered on top of the
subtitle-derived labels rather than replacing them. Lines the transcript doesn't cover keep
their exact in-game subtitle and fall back to scene-clustered (not fully chronological)
ordering.
