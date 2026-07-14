# Deriving hi32 for HZD Remastered voice streams — synthesis and test plan

*This report reconciles report1 (graph-stored / Decima-hash model) and report2 (Wwise Source ID model). It does not pick a winner blind. It states a unifying hypothesis, isolates the one factual contradiction that decides everything, and lays out a decision tree of cheap discriminating tests against your single known-good line (hi32 = `0x3e0f9d43`, source-id = `2022845001`).*

---

## TL;DR

- **Both prior reports agree on the foundation and disagree on one thing only:** *what hi32 is.* Report 1 says it is an opaque key stored in `streaming_graph.core` (a graph lookup, not a hash). Report 2 says it is a Wwise audio **Source ID** stored in the soundbank `.bnk`.
- **These are probably not mutually exclusive.** The likely truth that unifies both: **hi32 is the Wwise `.wem` Source ID, and that same value is reused as the high 32 bits of the 64-bit streaming key in `streaming_graph.core`** (with lo32 = locale/chunk/group sub-fields). If so, the `.bnk` and the graph reference the *same* number from two ends, and both reports are describing one mechanism.
- **One factual contradiction decides the whole thing and must be resolved first:** are `.wem` Source IDs (a) **30-bit FNV hashes of the GUID bytes** (report 1's claim, which it uses to *reject* Wwise) or (b) **tool-assigned, uniformly-distributed 32-bit IDs** (report 2's claim, which it uses to *confirm* Wwise)? Your measured fact — hi32 fills the full 32-bit range — is consistent with (b) and inconsistent with (a). See Open Item #1.
- **The fastest possible confirmation costs one command:** if odradek's exported `.wem` filename for your known line equals `0x3e0f9d43`, the Wwise-Source-ID model is correct and you are essentially done modelling. Run that first.

---

## 1. What both reports establish (treat as settled)

- HZDR runs on the **Forbidden-West-generation Decima** engine — same generation as HFW and DS2. This is why Decima Workshop 0.1.27 cannot open it and **odradek** can.
- The streaming layer is `LocalCacheWinGame/package/streaming_graph.core` + `streaming_links.stream`, with bulk bytes in `package.NN.MM.core.stream`. The 64-bit key resolves to **(package file, offset, length)**.
- **hi32 is not a hash of any dialogue field** (name / UUID / object GUIDs). This is the agreed explanation for your ~40-function null result — you were hashing the wrong inputs, in the wrong layer.
- The numeric **source-id `2022845001` (`0x788FB6A9`)** is an *input / join key / lead*, not the media-id itself.
- Audio is ATRAC9 `.wem` → VGAudio → WAV.
- **odradek (`odradek-game-hfw`) is the reference implementation.** Neither prior session could retrieve its verbatim Java (GitHub blocked `tree/`, `blob/raw`, code-search). The exact bit-arithmetic must be read from a local clone.

If anything below contradicts your actual HZDR files, your files win — odradek officially targets HFW 1.5.80.0, not HZDR, and minor format drift is possible.

---

## 2. The unifying hypothesis

The two reports look incompatible because each describes a different *layer* of the same pipeline:

```
dialogue line
   → Wwise Event (short-id; the 2022845001-type value)        [report 2's domain]
       → Action(Play) → Sound/SFX object
           → source/file ID  ===  hi32  ===  the .wem Source ID
                   │
                   └── reused as the HIGH 32 bits of the 64-bit streaming key
                         in streaming_graph.core                 [report 1's domain]
                              → (package.NN.core.stream, offset, length)
```

Under this model:
- **Report 2 is right about what hi32 *is*** — a Wwise Source ID, an authored/assigned value, not derivable by hashing dialogue. This explains the uniform 32-bit spread and the total absence of hash signal.
- **Report 1 is right about where the 64-bit key *lives*** — in `streaming_graph.core`, resolving to file/offset/length — but hi32 is not an *independent* opaque key; it is the Source ID surfacing again as the top half of the streaming key.
- **lo32** is then the sub-field structure report 2 flagged (locale / group / chunk index), which is why the *64-bit* key — not hi32 alone — is what indexes `package.01.00.core.stream`.

This is a hypothesis, not a finding. But it is **directly testable** (Section 4) and it dissolves the apparent conflict instead of forcing a coin-flip.

---

## 3. Open items that must be resolved (in priority order)

### Open Item #1 — the `.wem` Source ID contradiction *(decides everything)*
- **Report 1:** "other objects and `.wem` files get a **30-bit** FNV hash of the 128-bit GUID *bytes*" → a 30-bit value can't fill the 32-bit range, so Wwise is rejected.
- **Report 2:** "audio **Source IDs** are assigned per-file by the Wwise authoring tool, uniformly distributed across the 32-bit range" → not a hash at all.
- **Your measured fact:** hi32 is uniformly distributed across the full 32-bit range.
- **Why it matters:** if report 1's 30-bit-GUID-hash claim is correct, hi32 cannot be a `.wem` Source ID and the whole Wwise model collapses back to report 1's graph/Murmur model. If report 2 is correct, the unifying hypothesis stands.
- **How to settle it without theory:** open the known line's `.wem` in odradek and read its filename; inspect the HIRC `Sound`/source struct (`file_id`) for that clip; compare to `0x3e0f9d43`. The bytes on disk resolve this faster than reconciling two secondhand descriptions of Wwise internals.

*Note on the underlying Wwise nuance:* both claims are partially true in general Wwise — named objects (Events, Banks, Buses, States, Switches, Game Parameters) use **FNV-1 32-bit of the lowercased name**; unnamed HIRC objects can carry a hashed-GUID short-id; imported audio *sources* historically get assigned IDs. The question is specifically which rule HZDR's `.wem` Source IDs follow. Don't resolve it by argument — resolve it by reading one known file.

### Open Item #2 — is hi32 reused as the streaming key's high 32 bits?
Test by inspecting several known 64-bit keys (Section 4, Test C). Confirms or kills the unifying hypothesis.

### Open Item #3 — lo32 semantics
Once #2 is known, decode lo32 (locale / group / chunk). Needed only if you want to *synthesize* full keys rather than look them up.

---

## 4. Decision tree — discriminating tests against your oracle line

Run cheapest-first. Each test changes what you do next.

**Test A — odradek `.wem` filename == hi32? (cheapest, run first)**
- Clone and build odradek (`git clone https://github.com/ShadelessFox/odradek --recursive`; JDK 25; `./mvnw clean package`). Export your known line's audio.
- **If the exported `.wem` is named `3e0f9d43.wem` (or the ID equals `0x3e0f9d43`):** hi32 **is** the Wwise Source ID. Unifying hypothesis confirmed at the source-ID end. Go to Test C, then build the table via wwiser (Section 5, Track 2). *You are effectively done modelling.*
- **If it is not:** Wwise-Source-ID model is wrong or incomplete. Fall to Test B / Track 1.

**Test B — does `0x3e0f9d43` appear verbatim in the parsed `streaming_graph.core`?**
- Load `streaming_graph.core` via odradek's RTTI / object-tree dump. Find the locator array carrying 64-bit keys alongside offsets/lengths.
- **If your known entry appears verbatim (key → offset/length matches the line you already decoded):** the "derivation" is a **graph lookup**, not a hash. Abandon all hashing. Build {resource UUID → 64-bit key → (file, offset, length)} from the graph. (Report 1's Stage 2 outcome.)
- **If absent:** the key is stored encoded/packed, or derived; continue.

**Test C — is hi32 the high 32 bits of the 64-bit key? (resolves Open Item #2)**
- For several known lines, split the 64-bit key into hi32/lo32. Check hi32 == the line's media-id and look for structure in lo32 (constant, small-range, locale-correlated).
- **If hi32 == media-id consistently:** unifying hypothesis confirmed; lo32 decoding (Open Item #3) lets you synthesize keys directly.

**Test D — FNV-1 of the event name == source-id `2022845001`?**
- Compute FNV-1 32-bit (offset basis `2166136261` / `0x811C9DC5`, prime `16777619` / `0x01000193`, lowercased ASCII, `hash = (hash * prime) XOR byte`) of the event name string, if your dialogue data exposes one.
- **If it matches:** the source-id is the Wwise **Event** short-id — your join key into the bank. Proceed to wwiser join (Track 2).
- **If it does not match:** the dialogue references the sound by **GUID**, not by name-derived short-id; resolve via the HIRC object GUID directly.
- *Do not* apply FNV to the media-ids themselves — both reports agree that will never work.

**Test E — Decima path-hash hypothesis (parallel, cheap; report 1's Stage 3)**
- Only meaningful if A and B both come back negative (hi32 neither a stored Wwise ID nor a stored graph key). Implement **MurmurHash3-x64-128** (Peter Scott C port), input = lowercased candidate virtual path for the streamed wave asset **with a trailing `\0`**. Try the `.core` path, the `.core.stream` path, with/without language suffix; seed 0 first (Decima's documented convention), seed 42 as fallback; test the full 64-bit, each 64-bit half, and the top-32 slice against `0x3e0f9d43`.
- **If any candidate reproduces the oracle:** you have a derivable hash; validate across the full answer key.

---

## 5. Merged action plan (two parallel tracks, one oracle)

The two prior plans are complementary, not competing. Run both tracks; they cross-validate on the same known-good line.

**Track 1 — Graph (from report 1).** Parse `streaming_graph.core` with odradek RTTI → build {UUID → 64-bit key → (file, offset, length)}. Answers "where do the bytes live" regardless of how hi32 is derived. Covers Tests B and C.

**Track 2 — Soundbank (from report 2).** Extract the `.bnk` soundbanks (they travel as Decima resources wrapping Wwise banks; odradek handles them) → run **wwiser** (bnnm), load any `wwnames.txt` → dump banks to XML/TXTP → for each Event read the resolved Sound object's source/file ID → build {event short-id → source-id (= hi32)} → join to your dialogue table on the event short-id. Concrete struct reference: Morilli/bnk-extract `struct sound { uint32_t self_id; uint32_t file_id; uint8_t is_streamed; }` — `file_id` is the wem Source ID. Covers Tests A and D. For events mapping to multiple wems (random/sequence containers), wwiser exposes all candidates; disambiguate by language/switch context or by matching the wem already in the stream.

**Convergence:** both tracks must agree on your one known line — event short-id → `0x3e0f9d43` → the correct offset/length in `package.01.00.core.stream`. When they agree, scale to the full 67,853-entry answer key.

**Read-the-source step (settles all bit-arithmetic).** In the odradek clone, grep `odradek-game-hfw` for: `Streaming`, `streaming_graph`, `streaming_links`, `DataSource`, `Locator`, `StreamingRef`, `StreamSelector`, `package.`, and hashing primitives `Murmur`, `hash64`, `hash128`, `computeHash`, long `0x` constants. Trace `WaveResource` / `LocalizedSimpleSoundResource` → streamed-payload resolution in `odradek-export-wave` / `odradek-viewer-audio`. Whatever function maps a resource to (file, offset, length) is the definitive answer — lookup, hash, or both.

**Community / primary sources to mine in parallel:** the odradek Discord (`discord.gg/Gt4gkMwadB`) and ResHax Decima/HFW channels, where **id-daemon** (author of the HFW packing/extraction tools behind HFW Mod Manager — tools that rewrite `streaming_graph.core` and therefore must encode the key-assignment logic) and others reversed this exact format.

---

## 6. What each prior report contributed (provenance)

- **From report 1:** GDC prefetch/index architecture; the loose-file insight (why the byte-scan of 13 cores missed it — the index is in `package/`, not the scanned archives, and is stored encoded); the Decima MurmurHash3-x64-128 path-hash hypothesis with seed/NUL details; the staged plan with explicit "benchmark that changes the plan" framing; id-daemon / HFW Mod Manager / ResHax leads; `StreamingRef` + `LocalizedSimpleSoundResource` RTTI types.
- **From report 2:** the identification of hi32 as a Wwise **Source ID** and the reasoning from your evidence fingerprint (uniform spread, zero hash signal, distinct numeric source-id, ATRAC9 `.wem`); the concrete HIRC chain and real bnk-parser references (Morilli, Maddoxkkm); the wwiser → XML/TXTP workflow with the Total War worked example; the FNV-1 event-name test; the lo32 sub-field analysis.

---

## 7. Caveats (carried from both, plus synthesis risk)

- **The unifying hypothesis (Section 2) is unproven.** It is the most economical reconciliation of both reports and is directly testable, but it could be wrong — hi32 and the 64-bit streaming key may be independent. Test C decides this.
- **Open Item #1 is genuinely unresolved** at the level of "which Wwise rule governs HZDR `.wem` Source IDs." Both prior reports asserted incompatible Wwise internals; neither verified against an actual HZDR file. Resolve by reading bytes (Test A), not by argument.
- **No verbatim odradek source** was available to either prior session; exact class/method names, the precise key bit-layout, and any hash seed/input remain unconfirmed until the local clone is read.
- **HZDR may differ from HFW** despite the shared engine generation; validate every assumption against your real files and your one known-good line.
- **Container randomization:** events that map to multiple wems need switch/state context for exact single-line resolution — a per-line edge case, not a blocker for the bulk mapping.

---

*Bottom line: run Test A. One exported filename most likely collapses the entire question — and tells you whether report 1 or report 2 was right about the only thing they disagreed on.*
