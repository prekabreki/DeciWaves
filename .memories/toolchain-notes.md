---
description: Which third-party tools each game's audio pipeline actually needs and why — Wwise vs ATRAC9 decoders, an RTTI type-table reference for Forbidden-West-generation resources, and where ASR sits as an optional, GPU-gated stage
type: reference
---

Each game needs a different combination of tools past the pure-Python resource/archive
readers this project ships. None of these are vendored into the package; they're external,
separately-obtained tools the pipeline shells out to or reads reference data from.

## Decoders (game-specific, not interchangeable)

- **Death Stranding's audio payload is Wwise `.wem`** (see [[ds-wwise-wem-format]]) —
  needs a Wwise-aware decoder (`vgmstream-cli` or `ww2ogg`) to get to WAV. A generic
  Decima-only reader cannot decode this; it can only locate and extract the raw stream.
- **HZD Remastered and Forbidden West's audio payload is ATRAC9**, a different codec
  entirely — needs an ATRAC9 decoder (VGAudio-family tooling), not a Wwise decoder. Don't
  assume the DS decoder chain applies to the other two games; the two families need
  genuinely different decode tools, decided by which game's clip you're holding.
- **WAV to the final deliverable** goes through `ffmpeg`/`ffprobe` for MP3 encoding and for
  concatenating clips into continuous story-ordered reels.

## Forbidden-West-generation resource reference

Naming and interpreting Forbidden-West-generation (i.e. HZD Remastered and Forbidden West)
RTTI resource types benefits from an external type-table reference describing each type's
field layout and ordering — the community `odradek` project (an open-source Forbidden
West/Decima-2 reverse-engineering tool) is the practical source for this, both as generated
type-table data and as a source-level reference for how its own readers walk streaming and
RTTI structures. Treated strictly as read-only reference material to port logic *from*, not
as a runtime dependency — the pipeline's own readers are self-contained ports, not wrappers
around someone else's tool.

## ASR is an optional, install-gated stage

ASR (used for HZD's collision-bucket disambiguation and Forbidden West's within-group
subtitle-to-audio assignment) is the one stage with a real dependency footprint — it needs a
GPU-capable deep-learning stack that most of the rest of the pipeline doesn't. Keep it behind
an optional install extra rather than a hard dependency, so the base pipeline (parsing,
archive reading, catalog building, rendering) installs and runs anywhere, and only the ASR
step requires the heavier, CUDA-matched environment. Expect the ASR extra's pinned versions
to be sensitive to which CUDA-enabled build of the underlying deep-learning framework gets
installed — a mismatched build silently falls back to CPU rather than failing loudly, so
verify GPU availability after installing the extra, not just that installation succeeded.

## A general lesson that applies across all three games

Don't trust a resource-format parser until it's been checked to consume *exactly* the
declared size of a resource on several distinct real samples of that type. A parser that runs
without raising an exception but silently desyncs mid-object (mis-reading a field boundary)
will corrupt every field read after the desync point without any error signal — the
"declared size equals bytes actually consumed" check is what catches this, not the absence of
an exception.
