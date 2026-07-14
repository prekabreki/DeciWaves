import struct
from typing import BinaryIO, List
from deciwaves._vendor.pydecima.enums.DecimaVersion import DecimaVersion
from deciwaves._vendor.pydecima.resources.LootSlot import LootSlot
from deciwaves._vendor.pydecima.resources.InventoryItemComponentResource import InventoryItemComponentResource
from deciwaves._vendor.pydecima.resources.Resource import Resource
from deciwaves._vendor.pydecima.resources.structs.Ref import Ref
from deciwaves._vendor.pydecima._utils import parse_hashed_string


class InventoryLootPackageComponentResource(Resource):
    def __init__(self, stream: BinaryIO, version: DecimaVersion):
        Resource.__init__(self, stream, version)
        self.name = parse_hashed_string(stream)
        self.unk_ref = Ref(stream, self.version)
        assert (self.unk_ref.type == 0), "unk_ref populated"
        ref_count = struct.unpack('<I', stream.read(4))[0]
        self.loot_slot: List[Ref[LootSlot]] = [Ref(stream, self.version) for _ in range(ref_count)]
        self.inventory_item_component: Ref[InventoryItemComponentResource] = Ref(stream, self.version)

    def __str__(self):
        return '{}: {}'.format(self.type, self.name)
