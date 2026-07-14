from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.Resource import Resource


class SkeletonAnimationResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.data = stream.read(self.size - 16)
