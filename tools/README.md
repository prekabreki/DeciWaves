# tools/

Historical reverse-engineering scripts from the phase that discovered how HZD Remastered
binds a dialogue line to its audio stream (see docs/runtime-binding-plan.md and
.memories/hzd-structural-binding.md for how that investigation landed). Kept for
provenance, not because the shipped pipeline needs them.

**Superseded.** The `deciwaves hzd` CLI stages call none of these; the binding they were
built to find is solved offline now, by content fingerprinting, with no runtime probing
of a live game process required.

**Read-only stance.** Every script below ran against the author's own, legally owned game
install purely to observe engine behavior at runtime. None of them write to, patch, or
repack any game file. Not covered by tests, not installed with the package, not
maintained going forward -- expect them to bit-rot.

## Scripts

- `hzd_autodump.ps1` -- "capture the running game's memory, then scan it" loop: waits for
  the process, takes a full-memory dump (procdump, or the Windows comsvcs.dll MiniDump
  fallback), and runs `hzd_memscan.py` against each dump.
- `hzd_memscan.py` -- searches a captured memory dump for the line-to-stream-key binding:
  a known stream key sitting near a known resource GUID at a consistent byte offset.
- `hzd_extract_ids.py` -- builds the GUID/uuid index (line_id -> resource identifiers)
  that `hzd_memscan.py` searches memory for.
- `hzd_dstorage_hook.js` -- a Frida hook on the game's DirectStorage read calls, capturing
  which physical offsets the engine reads when a given line plays.
- `hzd_phys_to_key.py` -- maps a physical offset captured by the Frida hook back to the
  archive's logical offset and its candidate stream keys.
- `clean-hzd-dumps.ps1` -- deletes the (gitignored, multi-gigabyte) memory dumps written
  by `hzd_autodump.ps1`; needed because their ACLs can resist deletion from a normal,
  non-elevated session.

Note: the comsvcs.dll MiniDump fallback above is a full-process-memory dump technique some
antivirus heuristics flag. It dumps the game's own running process -- the same purpose
procdump serves, just via a technique built into Windows rather than a separate signed tool --
and was only ever run here against the author's own process.

`memory-index.ps1` and `regenerate-fixtures.py` also live here but are current,
maintained tooling, not part of the historical cluster above.
