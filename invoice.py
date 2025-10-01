# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder, Eval


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('invoice', 'Supplier Invoice'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    invoice = fields.One2Many('account.invoice', 'document', "Account Invoice",
        size=1, add_remove=[('document', '=', None)],
        context={
            'type': 'in',
            'company': Eval('document_company', -1),
        }, states={
            'invisible': (Eval('model_type') != 'invoice'),
        }, depends=['document_company', 'model_type'])

    def get_party(self, name):
        if self.model_type == 'invoice' and self.invoice:
            return self.invoice[0].party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party() + [
            ('invoice.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'invoice': 'Supplier invoice',
                })
        return types

    def guess_invoice(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')

        if self.model_type != 'invoice':
            return

        if self.party:
            pass


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_lines = fields.One2Many('papyrus.invoice.line', 'invoice', 'Papyrus Lines')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_modify_exclude.add('document')

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super(Invoice, cls).copy(invoices, default=default)


class PapyrusInvoiceLine(ModelSQL, ModelView):
    __name__ = 'papyrus.invoice.line'

    # TODO: Ideally we should remove the line when both the invoice and the document
    # are deleted
    document = fields.Many2One('papyrus.document', 'Document',
        ondelete='CASCADE')
    invoice = fields.Many2One('account.invoice', 'Invoice', ondelete='SET NULL')
    product_code = fields.Char('Product Code')
    description = fields.Text('Description')
    quantity = fields.Numeric('Quantity')
    unit_price = fields.Numeric('Unit Price')
    discount_rate = fields.Numeric('Discount (%)')
    taxes = fields.Char('Taxes')
    subtotal = fields.Numeric('Subtotal')
    product = fields.Many2One('product.product', 'Product')
    invoice_line = fields.Many2One('account.invoice.line', 'Invoice Line',
        ondelete='SET NULL')


class InvoiceDossier(Wizard):
    __name__ = 'invoice.dossier'

    start_state = 'open_'
    open_ = StateAction('papyrus.act_attachment_form')

    def do_open_(self, action):
        pool = Pool()

        try:
            SaleLine = pool.get('sale.line')
        except KeyError:
            SaleLine = None
        try:
            PurchaseLine = pool.get('purchase.line')
        except KeyError:
            PurchaseLine = None
        try:
            InvoiceLineStockMove = pool.get('account.invoice.line-stock.move')
        except KeyError:
            InvoiceLineStockMove = None

        invoice = self.record

        resources = set()
        resources.add(str(invoice))
        lines = []
        for line in invoice.lines:
            lines.append(line.id)
            if line.origin:
                if PurchaseLine and isinstance(line.origin, PurchaseLine):
                    resources.add(str(line.origin.purchase))
                if SaleLine and isinstance(line.origin, SaleLine):
                    resources.add(str(line.origin.sale))

        if InvoiceLineStockMove:
            invoice_stocks = InvoiceLineStockMove.search([
                ('invoice_line', 'in', lines),
                ])
            for invoice_stock in invoice_stocks:
                shipment = invoice_stock.stock_move.shipment
                if shipment:
                    resources.add(str(shipment))

        sub_domain = []
        for resource in resources:
            sub_domain.append(resource)

        domain = [('resource', 'in', sub_domain)]
        action['pyson_domain'] = PYSONEncoder().encode(domain)
        return action, {}

    def transition_open_(self):
        return 'end'
