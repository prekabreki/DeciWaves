from typing import BinaryIO
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.ImageStruct import ImageStruct
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class Texture(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        start_pos = stream.tell()
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        if self.size - (stream.tell() - start_pos) > 0:
            self.image_data = ImageStruct(stream, version)

    def __str__(self):
        streamed = hasattr(self.image_data, "size_of_stream") and self.image_data.size_of_stream > 0
        return f'{self.type}: {self.name}, {self.image_data.width}x{self.image_data.height}, ' + \
               f'{self.image_data.image_format.name}, {"streamed " if streamed else ""}' + \
               f'@{hex(self.image_data.stream_start) if streamed else "internal"}'
