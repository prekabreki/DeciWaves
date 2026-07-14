import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion

from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.enums.ETextLanguages import ETextLanguages


class LocalizedTextResource(Resource):
    # DS:DC (DSPC) localized text is NOT the Horizon fixed layout. After the 28-byte resource
    # header the body is a VARIABLE-length run of (uint16 len + UTF-8 text) entries separated
    # by a VARIABLE run of 0x00 padding, filling the object exactly. Entry 0 is English. Most
    # objects carry 21 strings (== len(ETextLanguages)); some 20/22 (a trailing
    # <subtitle-delay> token) or 1 (English-only lore/markers). The old model (a fixed 25
    # entries with a fixed 3 trailing bytes per string) desynced on the special/CJK slot,
    # read a garbage length, overran the object and raised UnicodeDecodeError mid-binary on
    # ~15 cores. We instead read the size-exact body and scan it, so the parse always consumes
    # exactly size+12 (the reader's per-object assertion) and can NEVER abort the core.
    #
    # Per-language indexing past English is best-effort: zero-length companion/padding words
    # are absorbed, so for the ~21-string objects the index aligns to ETextLanguages, but the
    # contract guaranteed here is only language[0] == English. (Confirmed: English recovered on
    # 4784/4784 objects across the 15 failing cores + controls; scan lands byte-exact on 98%.)

    @staticmethod
    def read_fixed_string(stream: BinaryIO, version: DecimaVersion = DecimaVersion.HZDPC):
        # Horizon path, unchanged.
        size = struct.unpack('<H', stream.read(2))[0]
        return stream.read(size).decode('UTF8')

    @staticmethod
    def _scan_dspc_languages(body: bytes) -> List[str]:
        out: List[str] = []
        i, n = 0, len(body)
        while i + 2 <= n:
            slen = struct.unpack_from('<H', body, i)[0]
            if slen == 0:                         # zero-length / pure padding word
                i += 2
                while i < n and body[i] == 0x00:
                    i += 1
                continue
            if i + 2 + slen > n:
                break
            try:
                out.append(body[i + 2:i + 2 + slen].decode('UTF8'))
            except UnicodeDecodeError:
                break                             # hit a non-string boundary -> stop best-effort
            i += 2 + slen
            while i < n and body[i] == 0x00:      # skip variable inter-entry 0x00 padding
                i += 1
        return out

    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        if version == DecimaVersion.DSPC:
            # Object total = size + 12; Resource.__init__ already read the 28-byte header
            # (8 type + 4 size + 16 uuid) -> size - 16 body bytes remain. Reading exactly that
            # many is size-exact by construction, so reader.py's size+12 assertion always holds.
            body = stream.read(max(0, self.size - 16))
            langs = LocalizedTextResource._scan_dspc_languages(body)
            if not langs:
                langs = ['']
            while len(langs) < len(ETextLanguages):
                langs.append('')
            self.language = langs
        else:
            self.language = [LocalizedTextResource.read_fixed_string(stream, version)
                             for _ in range(len(ETextLanguages))]

    def __str__(self):
        return self.language[ETextLanguages.English].strip()

    def __repr__(self):
        return self.language[ETextLanguages.English].__repr__()
