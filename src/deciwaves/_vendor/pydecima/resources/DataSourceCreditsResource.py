import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.CreditsRow import CreditsRow
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class DataSourceCreditsResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        row_count = struct.unpack('<I', stream.read(4))[0]
        self.rows: List[Ref[CreditsRow]] = [Ref(stream, self.version) for _ in range(row_count)]

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
