# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields


class ShipmentIn(metaclass=PoolMeta):
    __name__ = 'stock.shipment.in'
    document = fields.Many2One('papyrus.document', "Document")

    @classmethod
    def copy(cls, shipments, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super(ShipmentIn, cls).copy(shipments, default=default)
