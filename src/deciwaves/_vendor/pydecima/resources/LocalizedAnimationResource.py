import struct
from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref


class LocalizedAnimationResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.unk_1 = struct.unpack('<I', stream.read(4))[0]
        self.unk_2 = struct.unpack('<I', stream.read(4))[0]
        self.unk_3 = Ref(stream, self.version)
