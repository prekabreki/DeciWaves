"""Death Stranding 2 voice-line enumeration: which lines exist and where each
clip lives (the "list the lines" half of Phase 2, issue #359).

DS2's dialogue index is Forbidden West's in shape -- each
``LocalizedSimpleSoundResource`` occupies a width-12 block of locators, and the
12 slots are 12 languages. On an English install only slot 0's stream files
exist on disk, so slot 0 is the correct clip by construction.

**Where DS2 diverges from FW (issue #391).** FW's fast path accepts a streaming
group only if it is *arithmetically clean* -- ``locator_count == 12 * n_lssr``
exactly -- and then reads English at ``locator_start + 12*k``. DS2 routinely
packs dialogue into groups that also carry a handful of unrelated streaming
locators, so that equality fails and the whole group is discarded: on retail,
744 groups are clean but **47 more hold 8,145 further LSSRs**, one of them
rejected over a single stray locator in 2,173. Those extras are not distributed
evenly either -- they sit at the FRONT of the slice (group 54150 opens with five
non-dialogue locators before its 4,070 blocks begin), so simply relaxing the
equality and keeping the ``locator_start + 12*k`` arithmetic would bind every
clip in the group to the wrong line.

So DS2 locates dialogue by **content rather than by arithmetic**: it scans the
group's locator slice for windows matching a known 12-file *language cycle*
(:func:`language_cycles`). Because a cycle's slot 0 is a region's English
stream and appears nowhere else in the cycle, a matching window is unambiguous
-- the phase cannot be misread. On an arithmetically clean group the scan lands
on exactly ``locator_start + 12*k`` for every ``k`` (verified against all 744
retail clean groups), so **existing line_ids are unchanged** and an extract
resumes rather than re-deriving.

Measured on retail 2026-08-02: 8,776 -> 16,953 lines (1.93x), and the stream
files contributing rose from 7 to 9 -- ``remain`` (288 clips) and ``l800_fra``
(1) had produced nothing at all, because neither region owns a single clean
group for a cycle to be learned from. See ``.memories/ds2-audio-binding.md``.
"""
import os
import re
from typing import Iterator

from deciwaves.engine.pack.fw_fast_extract import (
    FastLine, LANGS, strip_cache_prefix,
)
from deciwaves.engine.pack.fw_rtti import type_hash

# The 12 stream packages a region ships, in language-slot order; slot 0 (package
# .01.00) is English. Measured: this NN order is byte-identical across all seven
# retail regions that own a clean group, which is what licenses applying it to
# the two that do not (`remain`, `l800_fra`).
VOICE_PACKAGE_NN = ("01", "02", "03", "04", "05", "07", "10", "11",
                    "16", "17", "18", "21")

# `<region>/package.NN.00.core.stream`, or the same at the package root (DS2
# ships English at the root -- there is no `en/` subdir, unlike FW).
_VOICE_STREAM_RE = re.compile(
    r"^(?:(?P<region>[^/]+)/)?package\.(?P<nn>\d+)\.00\.core\.stream$")


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


def language_cycles(graph) -> set[tuple[int, ...]]:
    """The 12-locator language cycle of every region that ships a full set.

    Each cycle is the tuple of ``graph.files`` indices for that region's
    :data:`VOICE_PACKAGE_NN` packages, in slot order -- i.e. exactly the
    ``file_index`` sequence a dialogue block walks. A region missing any of the
    12 contributes no cycle, so a partial region can never produce a
    short/misaligned match.
    """
    by_region: dict[str, dict[str, int]] = {}
    for i, f in enumerate(graph.files):
        m = _VOICE_STREAM_RE.match(strip_cache_prefix(f))
        if m:
            by_region.setdefault(m.group("region") or "", {})[m.group("nn")] = i
    return {
        tuple(slots[nn] for nn in VOICE_PACKAGE_NN)
        for slots in by_region.values()
        if all(nn in slots for nn in VOICE_PACKAGE_NN)
    }


def iter_ds2_lines(graph, package_dir) -> Iterator[FastLine]:
    """Yield a :class:`FastLine` for every DS2 English dialogue clip on disk.

    Scans each dialogue-bearing group for language-cycle windows (see the module
    docstring for why this replaces FW's arithmetic). ``lssr_index`` counts every
    window found, whether or not its English stream is on disk, so ids stay
    stable across installs.

    Raises ``KeyError`` when no voice stream is on disk or the graph declares no
    complete language cycle, so a wrong *package_dir* fails loudly instead of
    silently yielding zero lines.
    """
    on_disk = ds2_stream_indices(graph, package_dir)
    if not on_disk:
        raise KeyError(f"no DS2 voice stream found on disk under {package_dir!r}")
    cycles = language_cycles(graph)
    if not cycles:
        raise KeyError("no complete 12-language voice cycle in graph.files")

    lssr = type_hash("LocalizedSimpleSoundResource")
    file_index = graph.locators.file_index      # numpy view over all locators
    for grp in graph.groups:
        types = graph.type_table[grp.type_start:grp.type_start + grp.type_count]
        # Groups declaring no dialogue are skipped even when their locators
        # happen to spell a cycle: 244 retail asset groups do exactly that,
        # between them matching 486 windows that are not voice lines.
        if not int((types == lssr).sum()):
            continue
        seq = [int(v) for v in
               file_index[grp.locator_start:grp.locator_start + grp.locator_count]]
        k = j = 0
        while j + LANGS <= len(seq):
            if tuple(seq[j:j + LANGS]) not in cycles:
                j += 1                       # a non-dialogue locator; step past
                continue
            if seq[j] in on_disk:            # English present at block offset 0
                yield FastLine(f"g{grp.group_id}_{k:04d}", grp.group_id, k,
                               graph.locators[grp.locator_start + j])
            k += 1
            j += LANGS
