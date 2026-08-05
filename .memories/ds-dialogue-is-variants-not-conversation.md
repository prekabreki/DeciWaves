---
description: "DS `terminal` scenes are mutually-exclusive response VARIANTS mixed with real interview content, and `npc` is six per-character BARK BANKS — neither is a conversation, so scene-level keep/drop is the wrong unit and text-similarity dedupe does not find the redundancy"
type: gotcha
---

Learned 2026-08-05 while curating DS1 deliverable 1. Both categories look like scenes
and are not, which makes the obvious curation rules wrong in opposite directions.

## `terminal` (3,103 rows, 43 scenes) — variants + substance, interleaved

A prepper "interview" is not a conversation. Much of it is the delivery-feedback state
machine — the game plays exactly ONE of these depending on how the delivery went:

    "Luckily, our goods are in perfect condition."
    "Well, you did keep us waiting, but everything else seems to be in perfect order"
    "You're running behind, but... the cargo is still all right."

Three consequences:

1. **Excerpting from the head of a scene misrepresents it.** The acknowledgement lines
   sort first, so the first 6-10 lines of *every* interview read as worthless chatter
   while the same interview carries real material later ("I'll think about the UCA and
   if it's right for me"). A calibration sample built from scene heads made every
   prepper look cuttable — a pure sampling artefact. Sample spread across the scene.
2. **Text-similarity dedupe does not find them.** Clustering within-scene at 0.6
   ratio flagged only 7% as near-duplicates: the variants are semantically equivalent
   but lexically distinct. What it *did* catch was `lines_01_generic_terminal` (247
   rows) — genuine boilerplate ("You're looking well, Sam" / "You're doing great,
   Sam!"), which is a facility-chatter bank, not an interview, and is safe to drop
   wholesale.
3. **The redundancy that matters is CROSS-scene, not within-scene.** Codec briefings
   repeat verbatim across scenes (`m00050`/`m00060`/`m00065`, the UCA contract terms in
   `m00142`/`m00144`, the Craftsman briefing in `m00146`/`m00150`), so a within-scene
   check reports "clean" while the listener hears the same speech twice an hour apart.
   Dedupe must also handle **containment**: a truncated variant ending mid-sentence on
   an em-dash coexists with the full sentence (`lines_observatory_227`, 104 chars vs
   172). Keep the longer one.

## `npc` (490 rows) — six bark banks, not scenes

The scenes are `lines_cliff`, `lines_higgs`, `lines_mama`, `lines_artist`,
`lines_deadman`, `lines_amelie` — one per character, and they are NOT alike, so neither
a per-category drop nor a per-category keep is right:

| bank | rows | ≤3-word | what its LONG lines are |
|---|---|---|---|
| Cliff | 172 | 78% | battlefield commands, every one — drop the bank |
| Amelie | 4 | 100% | — drop the bank |
| Higgs | 174 | 47% | boss-fight taunts, some thematic |
| Mama | 86 | 36% | **real story monologue** ("I could hear my mother's heartbeat. Hers and Lockne's.") |
| Artist | 40 | 62% | companion chatter |
| Deadman | 14 | 57% | BB-pod fussing |

Dropping `npc` as a category throws away Mama's story lines; keeping it as a category
keeps 43 consecutive Cliff combat shouts. Rule per bank.

Related: [[ds-speech-spans-multiple-lines]], [[ds1-story-reel-composition]],
[[ds-render-honours-playlist-order]].
