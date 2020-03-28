# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields, ModelView
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction


class Document(metaclass=PoolMeta):
    'Papyrus Document'
    __name__ = 'papyrus.document'
    model_type = fields.Selection([
            (None, ''),
            ('invoice', 'Invoice'),
            ('sale', 'Sale'),
            ('shipment_in', 'Shipment In'),
            ], 'Model Type')
    invoice = fields.One2Many('account.invoice', 'document', "Account Invoice",
        size=1,
        states={
            'invisible': Eval('model_type') != 'invoice',
        }, depends=['model_type'])
    sale = fields.One2Many('sale.sale', 'document', "Sale", size=1,
        states={
            'invisible': Eval('model_type') != 'sale',
        }, depends=['model_type'])
    shipment_in = fields.One2Many('stock.shipment.in', 'document',
        "Shipment In", size=1,
        states={
            'invisible': Eval('model_type') != 'shipment_in',
        }, depends=['model_type'])

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//field[@name="invoice"]', 'states', {
                'invisible': Eval('model_type') != 'invoice',
                }),
            ('//field[@name="sale"]', 'states', {
                'invisible': Eval('model_type') != 'sale',
                }),
            ('//field[@name="shipment_in"]', 'states', {
                'invisible': Eval('model_type') != 'shipment_in',
                })
            ]

    def scan_engines(self):
        super().scan_engines()
        return ['text', 'textboxes']

    def get_record(self):
        record = super().get_record()
        if self.model_type == 'invoice':
            record, = self.invoice
        elif self.model_type == 'sale':
            record, = self.sale
        elif self.model_type == 'shipment_in':
            record, = self.shipment_in

        return record

    @fields.depends('model_type', 'invoice', 'sale', 'shipment_in')
    def on_change_model_type(self):
        if self.model_type:
            if not getattr(self, self.model_type):
                obj = getattr(self, '_get_%s' % self.model_type)()
                setattr(self, self.model_type, [obj])

        for type_, _ in self.__class__.model_type.selection:
            if type_ and self.model_type != type_:
                setattr(self, type_, [])

    def _get_invoice(self):
        Invoice = Pool().get('account.invoice')
        defaults = Invoice.default_get(list(Invoice._fields.keys()),
            with_rec_name=False)
        invoice = Invoice(**defaults)
        invoice.type = 'out'
        invoice.on_change_type()
        return invoice

    def _get_sale(self):
        Sale = Pool().get('sale.sale')
        defaults = Sale.default_get(list(Sale._fields.keys()),
            with_rec_name=False)
        sale = Sale(**defaults)
        return sale

    def _get_shipment_in(self):
        ShipmentIn = Pool().get('stock.shipment.in')
        defaults = ShipmentIn.default_get(list(ShipmentIn._fields.keys()),
            with_rec_name=False)
        shipment_in = ShipmentIn(**defaults)
        return shipment_in
