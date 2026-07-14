---
description: DS:DC dialogue is described by Decima resources but the encoded audio payload is Wwise .wem, not Decima-native audio — both layers have to be parsed
type: reference
---

Death Stranding (Director's Cut) dialogue is a two-layer format, and both layers matter:

- **Identification (speaker, subtitle, internal line name) is a Decima parsing job.**
  A `SentenceResource` carries refs to a voice path (the speaker code), a text resource
  (the English subtitle, among other languages), and a sound resource.
- **The encoded audio itself is Wwise `.wem`, not a Decima-native format.** The sound
  resource (`LocalizedSimpleSoundResource`) embeds, per spoken language, a literal virtual
  path ending in `.wem.<language>` (twelve language slots). The install is full of Wwise
  artifacts alongside the Decima resource tree, confirming the payload is genuinely Wwise-encoded.

## How the bytes are actually stored and located

A resource with its "has stream" flag set keeps its payload bytes in a *separate* packfile
entry from the resource's own metadata — the resource `.core` describes the clip, but the
clip's bytes live at a derived stream path. The convention: take the virtual path (here, the
`.wem.<language>` path from the sound resource), append `.core.stream`, and hash that whole
string with the same path-hashing scheme used to locate any other resource in the archive
(MurmurHash3 x64-128, seed 42, first 8 bytes of the digest, over the NUL-terminated UTF-8
path). The resulting hash resolves directly to an archive entry containing the raw Wwise
`.wem` bytes (a self-describing RIFF stream). Decoding that RIFF to WAV needs a Wwise-aware
decoder (`vgmstream-cli` or `ww2ogg`) — a generic Decima/RTTI resource reader cannot do it,
since the bytes aren't Decima-native audio at all.

This means: no general-purpose Decima archive browser recovers this audio by "export" alone,
because the stream lives outside the resource's own namespace and is keyed by a derived path
hash rather than being inline. A path-hash-aware packfile reader (open-format archive: a
small header, an encrypted/obfuscated file table keyed by the same path hash, per-entry
compressed spans) plus a Wwise decoder is the minimum toolchain for DS audio.

## Cutscenes are the one exception to per-line audio

Terminal/mission/NPC lines each have their own per-line `.wem`. Cutscene lines do not —
see [[ds-cutscene-audio]] for why their audio is a per-scene track instead.
