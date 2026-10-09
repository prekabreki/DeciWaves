---
description: "DS within-scene dedup drops encoding variants (normalized key) and re-splits (coverage match); radio/common is deliberately excluded from the re-split rule"
type: gotcha
---

`games/ds/selection.py` `filter_and_dedup` applies three within-scene rules, in order
(#419), and tags every dropped row with a `dupe_rule` field (`exact` / `normalized` /
`near-duplicate`) in the `--dupes` CSV:

- **exact** — the original `(scene, speaker, raw subtitle)` key.
- **normalized** — same key on the subtitle after casefolding, whitespace collapse and
  apostrophe/quote canonicalization (typographic vs ASCII vs the cp1252 mojibake of a
  typographic mark). Catches Class-1 encoding variants.
- **near-duplicate** — a line whose normalized text is >=85% covered by contiguous
  matches (each >=12 chars) against what the same speaker has already said earlier in the
  scene. Catches Class-2 re-splits, where the same content is segmented across different
  sentence boundaries so no half matches the other half.

**The near-duplicate rule is deliberately conservative and excludes `common`** (the
`lines_radio_nxt` / `lines_global` radio instruction bank). There, one template repeats
with a substituted destination ("Head to <place> and pick it up when you can."); coverage
matching merged 10 distinct instructions into false repeats. Scoped away from `common`,
the whole DS:DC catalog produced 43 near-duplicate drops, all sampled as true re-splits.
Encoding-variant (normalized) dedup still applies to radio.

Thresholds live as module constants with the measurements in comments. **Audit the
discard pile, not the keep pile** — this filter runs on every DS row, so a too-loose
threshold silently deletes dialogue and nothing fails.

Related: [[ds-terminal-scenes-are-response-banks]], [[ds-dialogue-is-variants-not-conversation]].
