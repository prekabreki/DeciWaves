import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.enums.ESentenceGroupType import ESentenceGroupType
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.SentenceResource import SentenceResource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class SentenceGroupResource(Resource):

    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        if version == DecimaVersion.DSPC:
            # DS:DC layout: <flag:u32> <count:u32> <count x Ref>. `flag` is 0 or 1 (verified
            # 113x0 / 67x1, and flag(4)+count(4)+count*17 == body on 180/180 objects). It is
            # NOT a hashed-string length: the old parse_hashed_string path read flag==1 as a
            # 1-char name + 4-byte hash, shifting the cursor by 5 and reading `count` as
            # ~500 million (the source of the 2 SentenceGroupResource parse failures). DS:DC
            # groups carry no textual name and omit Horizon's sentence_type enum.
            self.group_flag = struct.unpack('<I', stream.read(4))[0]
            self.name = ""
            self.sentence_type = None
        else:
            self.name = parse_hashed_string(stream)
            sentence_type = struct.unpack('<I', stream.read(4))[0]
            self.sentence_type = ESentenceGroupType(sentence_type)
        sentences_count = struct.unpack('<I', stream.read(4))[0]
        self.sentences: List[Ref[SentenceResource]] = [Ref(stream, self.version) for _ in range(sentences_count)]

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
