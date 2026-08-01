"""Death Stranding 2 voice-line enumeration: which lines exist and where each
clip lives (the "list the lines" half of Phase 2, issue #359).

DS2's dialogue index is Forbidden West's, exactly -- each
``LocalizedSimpleSoundResource`` occupies a width-12 block of locators, and the
12 slots are 12 languages. On an English install only slot 0's stream files
exist on disk, so slot 0 is the correct clip by construction; the entire
DS2-specific piece is computing "every ``graph.files`` index present on disk".
The resolver arithmetic itself transfers verbatim from
``fw_fast_extract.iter_english_lines`` -- see
``.memories/ds2-audio-binding.md``.
"""
import os
from typing import Iterator

from deciwaves.engine.pack.fw_fast_extract import (
    FastLine, iter_english_lines, strip_cache_prefix,
)


def ds2_stream_indices(graph, package_dir) -> set[int]:
    """Indices of ``graph.files`` whose file exists on disk under *package_dir*.

    The ``cache:package/`` device prefix is stripped (via
    ``fw_fast_extract.strip_cache_prefix``) before joining, so a graph entry
    like ``cache:package/l200_aus/package.39.00.core.stream`` resolves to
    ``<package_dir>/l200_aus/package.39.00.core.stream``.
    """
    return {
        i for i, f in enumerate(graph.files)
        if os.path.isfile(os.path.join(package_dir, strip_cache_prefix(f)))
    }


def iter_ds2_lines(graph, package_dir) -> Iterator[FastLine]:
    """Yield a :class:`FastLine` for every DS2 dialogue clip on disk.

    Delegates to ``fw_fast_extract.iter_english_lines`` with the on-disk index
    set as the accepted stream-file indices. That function raises ``KeyError``
    when the set is empty, so a wrong ``package_dir`` fails loudly instead of
    silently yielding zero lines.
    """
    return iter_english_lines(graph, ds2_stream_indices(graph, package_dir))
