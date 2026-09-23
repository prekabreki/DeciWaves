---
description: Structurally minimal, unencrypted, zero-entry .bin archive layout for PackIndex construction tests
type: recipe
---

# Minimal valid .bin archive for tests

`PackIndex.__init__` (`engine/pack/bin_index.py`) now fails fast (issue #414) when its
`data_dir` glob finds zero `*.bin` files, instead of silently building an empty index. Any
test whose `data_dir` fixture was previously an empty directory -- used to fake "archive
present but no matching stream" without doing real archive I/O -- needs at least one
structurally valid `.bin` file for `PackIndex`/`BinArchive.open_index()` to parse.

`BinArchive.open_index()` (`engine/pack/bin_archive.py`) accepts the smallest possible
unencrypted archive: 4 bytes magic (`0x20304050`) + 4 bytes key (unused when unencrypted)
+ 32 bytes of zeroed header dwords (`fileSize64`, `dataSize64`, `fileCount64=0`,
`chunkCount32=0`, `maxChunk32`). Zero file-table count and zero chunk-table count mean no
further bytes are read -- `open_index()` succeeds with an empty `file_table`.

```python
import struct
path.write_bytes(struct.pack("<II", 0x20304050, 0) + b"\x00" * 32)
```

`tests/conftest.py::write_empty_bin_archive(dest_dir)` wraps this; call it wherever a test's
`data_dir` fixture previously relied on being empty.
