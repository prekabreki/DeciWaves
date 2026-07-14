# Packaged data

ID/timing manifests and name rosters consumed by the pipeline — never game prose or audio.
Resolve at runtime via `deciwaves.data.packaged("<rel>")`.

## ds/data-file-list.txt

Filtered DS:DC virtual-path listing — the default `--file-list` for
`deciwaves.engine.catalog` (`deciwaves ds catalog`).

- **Game:** Death Stranding Director's Cut, PC/Steam.
- **Method:** reconstructed-from-proven-outputs. An earlier attempt to dump this listing
  with Decima Workshop's `paths` command against a project-less config OOM'd/misparsed
  and was abandoned. Instead of re-running an external tool, this file is the sorted,
  distinct `core_path` column already produced by a verified `deciwaves ds catalog` run
  against a real install (282 dialogue sentence cores) — no external tool required to use
  this repo.
- **Generated:** 2026-07-14.
- **Contents:** one virtual path per line, no header. 282 lines end `/sentences` under a
  `games.ds.profile.DS_CORE_PREFIXES` prefix (exactly what
  `engine.catalog.select_core_paths` selects) — pure paths, no dialogue text. The
  remaining 96 lines end `/simpletext` under `localized/sentences/voices/<stem>/` —
  exactly what `engine.speakers.SpeakerMap`'s `_DS_SIMPLETEXT_FILTER` selects (paths
  containing `sentences/voices/` and ending `/simpletext`) — pure paths, no speaker-name
  text; these were derived from the distinct `speaker_code` values of the same verified
  catalog run (`localized/voices/<stem>` -> `localized/sentences/voices/<stem>/simpletext`),
  not from any external tool. Both sets are inert to each other's consumer: the
  `/simpletext` lines don't end `/sentences` (or start with a `DS_CORE_PREFIXES` prefix)
  so `select_core_paths` ignores them, and neither set matches the
  `ds/sounds/wwise_cinematics_sound_resource/...` shape `subcut_core_index` looks for.
- **Scope note:** this listing only covers dialogue sentence cores and voice display-name
  cores. It does NOT cover the nested per-cut cutscene sound cores
  (`ds/sounds/wwise_cinematics_sound_resource/...`) that
  `games.ds.cutscene_audio.subcut_core_index` needs — those aren't present in a catalog
  run's `core_path` column, so they can't be reconstructed the same way. See
  `ds/cutscene_tracks.csv` below for how cutscene audio is bundled instead.
- To regenerate against a new game patch: re-run `deciwaves ds catalog` with a full
  packfile listing from your own tooling, then take the sorted distinct `core_path`
  values from the resulting `catalog.csv`, plus one `localized/sentences/voices/<stem>/simpletext`
  line per distinct `speaker_code` stem, and replace this file.

## ds/cutscene_tracks.csv

Pre-resolved cutscene voice-track listing — the default source for `deciwaves ds run`'s
story-order stage's `--cutscene-tracks` (`deciwaves.engine.story_order`). Columns:
`scene,status,track_index,voice_track_stream`. IDs and status codes only, no dialogue
text.

- **Method:** reconstructed-from-proven-outputs, copied verbatim from a verified
  `deciwaves ds cutscenes` run against a real install (170 scene/track rows; 164
  scenes resolved).
- **Generated:** 2026-07-14.
- Because this is bundled, `deciwaves ds run`'s default chain does not run the
  `cutscenes` stage at all. `deciwaves ds cutscenes` remains available standalone for
  anyone who wants to regenerate this file against their own install (e.g. after a
  game patch) — pass the result to `deciwaves ds order --cutscene-tracks <path>` to
  use it instead of the bundled one.

## ds/cutscene-keepspans.csv

Speech keep-spans per cutscene voice-track stream (trim manifest). Produced by the DS
cutscene-trim pass; timing/IDs only.

## fw/character_names.md, fw/burning_shores_names.md

Character-name rosters for ASR priming (WhisperX `initial_prompt` block).
