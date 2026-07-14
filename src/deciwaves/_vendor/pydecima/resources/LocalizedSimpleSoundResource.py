import struct
from typing import BinaryIO, List, Optional
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class LocalizedSimpleSoundResource(Resource):
    DSPC_AUDIO_LANGUAGES = ["english", "french", "spanish", "german", "italian",
                            "portuguese", "russian", "polish", "japanese",
                            "latamsp", "latampor", "greek"]

    class SoundInfo:
        def __init__(self, stream: BinaryIO):
            self.size_1 = struct.unpack('<I', stream.read(4))[0]
            self.sample_count = struct.unpack('<I', stream.read(4))[0]
            self.unk_3 = struct.unpack('<I', stream.read(4))[0]
            assert (self.unk_3 == 0)
            self.start = struct.unpack('<I', stream.read(4))[0]
            self.unk_5 = struct.unpack('<I', stream.read(4))[0]
            assert (self.unk_5 == 0)
            self.size_2 = struct.unpack('<I', stream.read(4))[0]
            self.unk_7 = struct.unpack('<I', stream.read(4))[0]
            assert (self.unk_7 == 0)
            assert (self.size_1 == self.size_2), "size 1 and 2 don't match"

    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        start_pos = stream.tell()
        Resource.__init__(self, stream, version)
        if version == DecimaVersion.DSPC:
            self._parse_dspc(stream, start_pos)
            return
        # ---- existing Horizon parse below (unchanged) ----
        self.name = parse_hashed_string(stream)
        self.unk_floats_1: List[float] = [struct.unpack('<f', stream.read(4))[0] for _ in range(17)]
        self.unk_bytes_2 = stream.read(17)
        self.unk_floats_3: List[float] = [struct.unpack('<f', stream.read(4))[0] for _ in range(9)]
        self.unk_bytes_4 = stream.read(3)
        self.state_relative_mix = Ref(stream, self.version)
        self.sound_preset = Ref(stream, self.version)
        filename_len = struct.unpack('<I', stream.read(4))[0]
        self.sound_filename = stream.read(filename_len).decode('UTF8')
        self.language_flags = struct.unpack('<H', stream.read(2))[0]
        assert (self.language_flags <= 0xFFF), "unrecognized language flag"
        self.unk_byte_5 = stream.read(1)
        self.audio_type = struct.unpack('<b', stream.read(1))[0]
        # 9: at9
        # b: mp3
        # d: at9, TODO: Figure out what's different from 9
        # f: aac, ps4-only
        assert (self.audio_type in [0x09, 0x0b, 0x0d, 0x0f]), f"unrecognized sound type {self.audio_type}"
        self.unk_bytes_6 = stream.read(4)
        self.sample_rate = struct.unpack('<I', stream.read(4))[0]
        self.bits_per_sample = struct.unpack('<H', stream.read(2))[0]
        self.bit_rate = struct.unpack('<I', stream.read(4))[0]
        self.unk_short_8 = struct.unpack('<H', stream.read(2))[0]
        self.unk_short_9 = struct.unpack('<H', stream.read(2))[0]
        self.sound_info: List[Optional[LocalizedSimpleSoundResource.SoundInfo]] = list()
        for i in range(12):
            if self.language_flags & (1 << i) != 0:
                self.sound_info.append(LocalizedSimpleSoundResource.SoundInfo(stream))
            else:
                self.sound_info.append(None)

    def _parse_dspc(self, stream, start_pos):
        end = start_pos + self.size + 12
        body = stream.read(end - stream.tell())
        self.raw_dspc = body
        self.wem_paths = self._extract_wem_paths(body)

    @staticmethod
    def _extract_wem_paths(body: bytes):
        langs = LocalizedSimpleSoundResource.DSPC_AUDIO_LANGUAGES
        found = {}
        # Scan for u32 LE length-prefixed UTF-8 strings that are localized wem paths.
        # Pure regex scanning fails here because the UUID byte immediately after each
        # length-prefixed string can be 0x75 ('u'), causing the regex to read e.g.
        # "englishu" as the language name.  Reading via the length prefix is exact.
        i = 0
        while i + 4 <= len(body):
            length = struct.unpack_from('<I', body, i)[0]
            # Sanity-check: real paths are 80-300 bytes; skip obviously wrong lengths.
            if 80 <= length <= 300 and i + 4 + length <= len(body):
                chunk = body[i + 4: i + 4 + length]
                if chunk.startswith(b'localized/') and b'.wem.' in chunk:
                    try:
                        s = chunk.decode('utf-8')
                        for lang in langs:
                            if s.endswith('.wem.' + lang) and lang not in found:
                                found[lang] = s
                                break
                    except (UnicodeDecodeError, ValueError):
                        pass
            i += 1
        return [found.get(l, "") for l in langs]

    def __str__(self):
        return '{}: {}'.format(self.type, self.name if hasattr(self, 'name') else self.type)
