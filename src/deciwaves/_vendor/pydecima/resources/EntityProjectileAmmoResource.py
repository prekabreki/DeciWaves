from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
import struct
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima._utils import parse_hashed_string


# TODO: Unfinished


class EntityProjectileAmmoResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        start_pos = stream.tell()
        Resource.__init__(self, stream, version)
        stream.seek(start_pos + 12)
        self.unk1 = struct.unpack('<h', stream.read(2))[0]
        self.uuid = stream.read(16)
        self.name = parse_hashed_string(stream)
        stream.seek(start_pos)
        self.data = stream.read(self.size + 12)

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
