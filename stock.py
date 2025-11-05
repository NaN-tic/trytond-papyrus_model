# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool, PoolMeta
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
        return super()._search_party(clause) + [
            ('shipment_in.supplier',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'shipment_in': 'Incoming Supplier Shipment',
                })
        return types

    def guess_shipment_in_warehouse(self, shipment):
        Move = Pool().get('stock.move')

        # Only if there are moves and all go to the same location
        # we can guess the warehouse
        moves = Move.search([
                ('company', '=', self.company),
                ('state', '=', 'draft'),
                ('from_location', '=', shipment.supplier.supplier_location),
                ('to_location.type', '=', 'storage'),
                ])
        if not moves:
            return
        location = moves[0].to_location
        for move in moves:
            if move.to_location != location:
                return
        return location.warehouse

    def guess_shipment_in(self):
        if not self.company or self.shipment_in:
            return

        party = self.guess_party('supplier')
        if not party:
            return
        shipment = self._get_shipment_in()
        shipment.supplier = party
        shipment.on_change_supplier()
        if not shipment.warehouse:
            shipment.warehouse = self.guess_shipment_in_warehouse(shipment)
            if not shipment.warehouse:
                return
        shipment.effective_date = self.guess_date()
        shipment.document = self
        shipment.save()
        self.guess_employee([('shipment_in.supplier', '=', party)])



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
