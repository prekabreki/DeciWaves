from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
import struct
from deciwaves._vendor.pydecima.resources.CreditsColumn import CreditsColumn
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class CreditsRow(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        column_count = struct.unpack('<I', stream.read(4))[0]
        self.columns: List[Ref[CreditsColumn]] = [Ref(stream, self.version) for _ in range(column_count)]
        self.style = Ref(stream, self.version)
        self.unk_1, self.unk_2 = struct.unpack('<bb', stream.read(2))

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
