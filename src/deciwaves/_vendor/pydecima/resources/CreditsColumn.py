from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
import struct
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string, read_utf16_chars


class CreditsColumn(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        name_len = struct.unpack('<I', stream.read(4))[0]
        self.credits_name = read_utf16_chars(stream, name_len)
        self.style = Ref(stream, self.version)
        self.style_2 = Ref(stream, self.version)
        self.unk = Ref(stream, self.version)
        assert self.unk.type == 0

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
