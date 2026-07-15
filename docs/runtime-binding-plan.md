# Runtime plan: recover the line → stream binding

> **Historical.** This runtime, memory-instrumentation route was superseded before it was
> needed. HZD Remastered's shipped voice binding is the offline `(A, B)` structural join +
> ASR-fallback approach in `docs/asr-binding-plan.md` (see `docs/architecture.md`'s
> Horizon Zero Dawn Remastered section), not a runtime crack of `hi32`. Forbidden West is
> the one of the three games that actually ships a streaming-graph positional index (see
> `docs/architecture.md`'s Horizon Forbidden West section) — HZDR does not, which is why
> this document explored recovering the binding from engine memory in the first place. The
> **Status** line, strategies, tooling, and exit gate below are a historical snapshot, not
> current state or an outstanding task.

**Status:** static routes exhausted (see the oracle and DirectStorage findings below). No on-disk
table maps a resource to its stream key; HFW's resolver is positional over a `streaming_graph.core`
that HZDR does not ship. The binding therefore exists only **in engine code / engine RAM at runtime**.
No Denuvo, so instrumentation is clean.

**Guiding principle: instrument ONCE, do NOT write a per-line tail.** A tail that logs reads as the
game plays cannot reach 67k lines. We want either (1) the *algorithm* (one breakpoint → apply offline
to all 67k) or (2) the *resident resolved map* the engine builds (one memory scrape → all entries).
A continuous tail is only a last-resort source of a few ground-truth pairs to validate a hypothesis.

## The oracle (known-good, for filtering / validation)
| field | value |
|---|---|
| line | `MQ010_cut_Prologue_Dial_225` |
| SENTENCE uuid | `573fa322-aed1-4fdc-bf93-2025218ff6c4` |
| SoundResource GUID (raw 16B) | `13 f9 53 2a 11 e9 4b 6f be 26 66 5e 27 bf 4c 3e` |
| stream key (u64) | `0x3e0f9d4305030200` (hi32 `0x3e0f9d43`, lo32 `0x05030200`) |
| archive | `package.01.00.core.stream` |
| **logical** offset | `133081218` = `0x07EEA882` |
| length | `1338916` = `0x146E24` |

Search needles in process memory: the **u64 key** `0x3e0f9d4305030200`, the **logical offset**
`0x07EEA882`, the **GUID** raw bytes, the **length** `0x146E24`. Reaching the line in-game: New Game →
prologue naming-ceremony cutscene (early; minutes in).

⚠️ **Logical vs physical offset.** `133081218` is the DSAR *logical* offset (what the locator stores).
The actual disk/DirectStorage read happens at a *physical* (compressed-chunk) offset after DSAR
translation — so do NOT filter a raw file-read on `133081218`. Filter higher up (the locator
lookup / key construction) or on the file handle for `package.01.00.core.stream` + timing.

## HZDR streams via DirectStorage — CONFIRMED (`dstorage.dll` + `dstoragecore.dll` v1.2.2311.1405)
`LocalCacheDX12` + `DSAR` (DirectStorage ARchive) ⇒ the engine streams through `dstorage.dll`
(Microsoft DirectStorage 1.2). The read goes through `IDStorageQueue::EnqueueRequest(DSTORAGE_REQUEST*)`
— the cleanest hook point. Vtable indices (after IUnknown 0/1/2): `IDStorageFactory::CreateQueue`=3,
`OpenFile`=4; `IDStorageQueue::EnqueueRequest`=3. `DSTORAGE_REQUEST` (x64) FILE-source layout:
`Options@0 (8B; bit0 SourceType 0=FILE)`, `Source.File{ IDStorageFile*@8 ; UINT64 Offset@16 ; UINT32 Size@24 }`.
These are encoded in `tools/hzd_dstorage_hook.js`. The hook also maps `IDStorageFile* → path` via
`OpenFile`, so reads can be filtered to `package.01.00.core.stream`.

## Strategy A — memory scrape of the resident resolved map (try first; one shot, full coverage)
The disk hunt proved GUID and key are NOT co-located on disk. But at **runtime** the engine must build
the association in RAM to play the right audio. So:
1. Launch, reach a state where the prologue resources are resident (the cutscene, or just past it).
2. Pause the process; snapshot memory (Cheat Engine / ReClass.NET / `MiniDumpWriteDump`).
3. Scan the snapshot for the **GUID bytes**; within a window around each hit, look for the **u64 key
   `0x3e0f9d4305030200`** or the **logical offset `0x07EEA882`**. A hit = the resolved binding
   structure. Map its record stride/layout (GUID → key/locator) with ReClass.
4. Dump the whole structure → resource-GUID → key for every resident line. Join to the catalog
   (which has SENTENCE/GUID per line) → offline render.
- **Coverage caveat:** if the engine resolves lazily (per scene), one menu/prologue dump won't hold
  all 67k. But scene-load batches many lines at once → bounded by ~780 scene cores, not 67k lines.
  Strategy B tells us whether resolution is eager or lazy.

## Strategy B — one breakpoint to recover the algorithm (definitive)
1. Hook `IDStorageQueue::EnqueueRequest` (or the fallback read) on the `package.01.00.core.stream`
   source. Trigger the prologue line.
2. On the hit whose request resolves to the oracle clip, **walk the stack**: find where
   `(archive, offset 0x07EEA882, length 0x146E24)` came from — the locator entry — and what 64-bit
   value indexed it (expect `0x3e0f9d4305030200`), and what the engine read from the resource to
   produce that value. This reveals whether the key is: a field somewhere we mis-parsed, a positional
   counter, or a lookup into a structure built at load (and from what input).
3. Output: the resolution rule + the in-RAM structure's address/layout (which makes Strategy A's
   scrape trivial and tells us eager vs lazy).

## Strategy C — validation tail (fallback only)
If A/B yield a *hypothesis* needing confirmation, log `(resolved key, offset)` for the handful of
lines that actually play, to build ground-truth `line → key` pairs. Never the primary path
(no full coverage).

## Tooling
- **x64dbg** — breakpoints, stack walks, conditional bp on the request struct (free, scriptable).
- **Frida** — scripted JS hook on `dstorage.dll` exports / `EnqueueRequest`; dump `DSTORAGE_REQUEST`.
- **Cheat Engine + ReClass.NET** — memory snapshot, structure mapping, table dump (Strategy A).
- **API Monitor** — quick first look at which I/O / DirectStorage APIs the process uses.

## Pre-launch prep (make the launch a single deliberate shot, not fishing)
- [ ] Confirm `dstorage.dll` present + version; get `EnqueueRequest` / `DSTORAGE_REQUEST` layout for that version.
- [ ] Pre-write the Frida/x64dbg script (filter: file == `package.01.00.core.stream`; flag offsets/sizes).
- [ ] Pre-write a memory-scan probe (needles: GUID, `0x3e0f9d4305030200`, `0x07EEA882`, `0x146E24`).
- [ ] Know the fast route to the prologue line; have a save just before it if possible.

## Exit gate
Reproduce `Dial_225 → 0x3e0f9d4305030200` from the recovered rule (or read it straight from the
dumped map), validate against ≥20 more lines, then apply offline: `line → key → clip` for all 67k →
unblocks the transcript-ordered, speaker/subtitle-labelled MP3 render.

## Turnkey artifacts (built + tested 2026-06-26 — see also tools/)
DirectStorage version, vtable indices, struct offsets, and the oracle physical→key mapping are all
verified, so the launch is a single deliberate shot, not fishing.
- **`tools/hzd_extract_ids.py`** (Strategy A prereq) — emits `out/hzd/line_ids.csv`
  (`line_id, sound_resource_guid, sentence_uuid`) for all ~67.4k lines; the GUID index the scanner needs.
- **`tools/hzd_memscan.py`** (Strategy A) — data-driven scan of a process minidump: valid stream-key set
  (locator hashes) × GUID/uuid set (line_ids.csv); finds a key adjacent to a known GUID, detects the
  repeated delta = record stride, sweeps all key-hits → recovered `line → key` bindings (joined to
  catalog.csv). Fast numpy core, pure-function units (`tests/test_hzd_memscan.py`); exit 0/1/2.
- **`tools/hzd_autodump.ps1`** (Strategy A driver) — hands-off capture loop: waits for the process,
  full-dumps periodically (procdump/comsvcs), scans each, accumulates `hzd_bindings.csv`. See above.
- **`tools/hzd_dstorage_hook.js`** (Strategy B/C) — Frida hook on DirectStorage; logs
  `(file, physOffset, size)` for the target stream + a backtrace into fullgame.dll for the first reads.
- **`tools/hzd_phys_to_key.py`** (Strategy C glue) — maps a captured **physical** offset → DSAR chunk →
  locator **key(s)**. Round-trips the oracle against the real install (`tests/test_hzd_phys_to_key.py`).

## Hands-off autodump (Strategy A, fully automated — preferred first attempt)
Turnkey loop that needs no debugger and no manual timing. Three steps for the user:

1. **Run the script** (PowerShell, ideally *as Administrator* so the dump succeeds):
   ```powershell
   .\tools\hzd_autodump.ps1
   ```
   It waits for the game process, so start it *before* launching the game.
2. **Launch & play** into dialogue scenes (the prologue naming ceremony is the
   known-good oracle scene). The script captures a full-memory dump every ~25 s
   (default `-MaxDumps 8`), scans each one, and accumulates results.
3. **Send back `hzd_bindings.csv`** — one row per recovered line:
   `line_id, stream_key, hi32, kind, speaker_name, subtitle_en`.

### What each tool does
- **`tools/hzd_extract_ids.py`** — *prereq, run once.* Walks every sentence core
  (same iteration as `games.hzd.catalog`) and emits **`out/hzd/line_ids.csv`**
  (`line_id, sound_resource_guid, sentence_uuid`, GUIDs as 32-char hex in raw
  on-disk order). This is the GUID index the scanner hunts for in RAM; it joins to
  `catalog.csv` by `line_id`. Build it with
  `PYTHONPATH=src .venv\Scripts\python.exe tools\hzd_extract_ids.py`.
  (~67.4k rows; the oracle row is `MQ010_cut_Prologue_Dial_225,13f9532a…,573fa322…`.)
- **`tools/hzd_memscan.py`** — scans a dump for resident binding records. Builds the
  valid stream-key set (~67.8k `package.01.00.core.stream` locator hashes) and the
  GUID/uuid set (from `line_ids.csv`), then mmaps the dump, finds every 8-byte
  (and 4-byte) aligned slot holding a valid key (numpy `searchsorted`), and within
  ±512 B of each key looks for a known GUID/uuid. A `delta` (guid_off − key_off)
  repeated across lines = the record stride; it then sweeps every key hit at that
  delta → the recovered `line → key` bindings, joined to `catalog.csv`.
- **`tools/hzd_autodump.ps1`** — the capture loop: waits for the process, dumps with
  `procdump -ma` (if on PATH / in `tools\`) else the built-in
  `comsvcs.dll, MiniDump … full`, scans each dump, keeps dumps that yield bindings
  (renamed `hzd_hit_<n>.dmp`) and deletes scan-misses unless `-KeepAll`.

### Exit codes (memscan, surfaced by autodump's final guidance)
- **0** — bindings recovered (a consistent delta was found and swept). Done: use
  the table.
- **1** — GUIDs/uuids were resident but **no consistent key↔GUID delta** → the
  binding record is **pointer-linked**, not byte-adjacent. Pivot to the Frida hook
  (`tools/hzd_dstorage_hook.js`, Strategy B) to find the structure via the resolver.
- **2** — **no relevant data resident** (no key hit or no GUID hit) → the dump was
  too early / not in a dialogue scene. Dump again while a scene is playing, or raise
  `-MaxDumps` / lower `-Interval`.

### Caveats
- Full dumps are multi-GB; without `-KeepAll` at most ~1 miss-dump exists at a time.
- "Access is denied" on dump → run the terminal **as Administrator**.
- The `comsvcs.dll` MiniDump method can be flagged by AV (benign here).
- The delta detector needs **≥2 resident lines** to confirm a stride, so dump a
  scene with several lines loaded (any real dialogue scene qualifies).

## Runbook (the single launch — manual / Frida, fallback to the autodump above)
1. `frida -f "<install>/HorizonZeroDawnRemastered.exe" -l tools/hzd_dstorage_hook.js --runtime=v8`
   (or launch + `frida -n HorizonZeroDawnRemastered.exe -l ...`). Confirm the factory/queue hooks log.
2. New Game → play into the prologue naming-ceremony cutscene. Watch the `[READ]` lines for
   `package.01.00.core.stream`; note the first backtraces (key-construction leads in fullgame.dll).
3. While the cutscene resources are resident, create a full minidump (Task Manager → right-click →
   *Create dump file*, or `procdump -ma`).
4. Offline: `python tools/hzd_memscan.py <dump>` → look for a repeated GUID→key delta (Strategy A win),
   and `python tools/hzd_phys_to_key.py <physOffset>` on captured reads → ground-truth `line→key` pairs.
5. With the rule or the map: extend to all 67k, then render.
