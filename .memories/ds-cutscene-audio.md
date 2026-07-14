---
description: DS story cutscenes are real-time in-engine (not pre-rendered video), their dialogue audio is a handful of per-scene Wwise voice tracks rather than per-line clips, and the grunt/dead-air trim is a speech-region-keep technique, not silence detection
type: reference
---

## Cutscenes are in-engine, not Bink video

Story cutscene dialogue sits in the same Decima `localized/` resource tree as codec and
terminal chatter — it is **not** encoded as pre-rendered video. The distinction between a
cutscene line, a terminal line, and an NPC line is purely which internal scene/name prefix its
`SentenceResource` carries; the parsing and extraction pipeline is identical for all of them.
Genuine pre-rendered video (studio/logo intros, recaps, credits) is a separate, much smaller
asset pool and is out of scope for the dialogue pipeline.

## Cutscene audio is per-scene, not per-line

Every cutscene `SentenceResource` has a null sound ref *by design* — unlike terminal/NPC
lines, a cutscene line's audio is not its own clip. Instead, a cutscene scene's dialogue lives
in a small number of **per-scene Wwise voice tracks**: one continuous track per scene per
language, occasionally split per character or per camera sub-cut, stored under a dedicated
cinematics-sound-resource area of the install (separate from the per-line sound resources).

Resolution path: from a cutscene's scene identifier, locate that scene's cinematics sound
resource core (camera/sub-cut scenes nest one directory deeper than single-cut scenes). That
core embeds the literal virtual paths of its audio tracks as plain length-prefixed strings —
music/SFX tracks alongside the dialogue voice track(s). Match the voice-track path for the
target language (truncate exactly at the language suffix; trailing bytes belong to the next
field and will corrupt the path if left in), then resolve that path's stream the same way any
other stream resolves (see [[ds-wwise-wem-format]]). One gotcha: cinematics streams can carry
a few trailing bytes past their declared RIFF size, which some Wwise decoders reject as
"broken" until the stream is trimmed to the declared size before decoding.

**Implication for rendering:** a cutscene's playable unit is the whole-scene voice track(s),
played continuously in order — not a per-line concatenation. The catalog's per-line cutscene
rows still carry useful labeling (speaker, subtitle, ordering) even though the audio itself is
scene-level.

## Trimming grunts and dead air from whole-scene tracks

Whole-scene voice tracks include grunts, breaths, and dead air between lines that a
line-by-line reel wouldn't have. The obvious tools for trimming this fail for the same reason:
grunts are **loud** and **voiced**, so energy-threshold silence detection never flags them, and
a plain voice-activity detector keeps them too (they read acoustically as speech). Cutting
grunts is a *speech-content* problem, not a silence or voice-activity problem.

**Working approach — speech-region keep, by omission.** Run an ASR model over the track to
find the intervals that contain actual recognized words (not merely "voiced" audio), then keep
only those intervals — padded by a few hundred milliseconds and with small gaps merged — and
let everything else (grunts, breaths, dead air) fall away by omission. If a track's total kept
speech falls below roughly a second, drop the whole track (it's pure non-speech vocalization).
Known limits: a grunt sitting *inside* a spoken interval survives untouched, and an
unusually loud grunt that the ASR's own voice-activity gate mistakes for speech survives too.

**Rejected alternative:** forced alignment of the audio against the known subtitle text is more
precise (it would catch grunts inside spoken intervals) but costs considerably more to build
than the "cut the egregious stretches, hand-polish the rest" bar actually requires.
