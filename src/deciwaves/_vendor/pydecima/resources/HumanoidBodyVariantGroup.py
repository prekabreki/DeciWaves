import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.HumanoidBodyVariant import HumanoidBodyVariant
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class HumanoidBodyVariantGroup(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        body_variants_count = struct.unpack('<I', stream.read(4))[0]
        self.body_variants: List[Ref[HumanoidBodyVariant]] = \
            [Ref(stream, self.version) for _ in range(body_variants_count)]

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
