import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.HashedString import HashedString
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class PrefetchList(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        paths_count = struct.unpack('<I', stream.read(4))[0]
        self.paths: List[HashedString] = [parse_hashed_string(stream, True) for _ in range(paths_count)]
        sizes_count = struct.unpack('<I', stream.read(4))[0]
        assert (paths_count == sizes_count), "differing number of paths and sizes"
        self.sizes = [struct.unpack('<I', stream.read(4))[0] for _ in range(sizes_count)]
        indices_count = struct.unpack('<I', stream.read(4))[0]
        self.indices = [struct.unpack('<I', stream.read(4))[0] for _ in range(indices_count)]
