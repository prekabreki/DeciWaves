import struct
from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.LocalizedSimpleSoundResource import LocalizedSimpleSoundResource
from deciwaves._vendor.pydecima.resources.LocalizedTextResource import LocalizedTextResource
from deciwaves._vendor.pydecima.resources.VoiceResource import VoiceResource
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


# TODO: Unfinished
class SentenceResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        # DS:DC drops the leading name hashed-string that Horizon carries here; the rest
        # (unk_int, two bytes, then sound/animation/text/voice refs) matches. Verified
        # byte-exact on real DS:DC sentences.core files.
        if version == DecimaVersion.DSPC:
            self.name = None
        else:
            self.name = parse_hashed_string(stream)
        self.unk_int = struct.unpack('<I', stream.read(4))[0]
        self.unk_byte_1 = struct.unpack('<b', stream.read(1))[0]
        self.unk_byte_2 = struct.unpack('<b', stream.read(1))[0]
        self.sound: Ref[LocalizedSimpleSoundResource] = Ref(stream, self.version)
        self.animation: Ref = Ref(stream, self.version)
        self.text: Ref[LocalizedTextResource] = Ref(stream, self.version)
        self.voice: Ref[VoiceResource] = Ref(stream, self.version)

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
