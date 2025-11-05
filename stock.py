# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields
from trytond.pyson import Eval


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('shipment_in', 'Shipment In'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    shipment_in = fields.One2Many('stock.shipment.in', 'document',
        "Shipment In", size=1, add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'shipment_in',
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('shipment_in')

    def get_party(self, name):
        if self.model_type == 'shipment_in' and self.shipment_in:
            return self.shipment_in[0].supplier.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party() + [
            ('shipment_in.supplier',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'shipment_in': 'Incoming Supplier Shipment',
                })
        return types

    def guess_shipment_in(self):
        pass


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
        return super().copy(shipments, default=default)
