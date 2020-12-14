# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
    document = fields.Many2One('papyrus.document', "Document")

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._check_modify_exclude += ['document']


class InvoiceDossier(Wizard):
    __name__ = 'invoice.dossier'

    start_state = 'open_'
    open_ = StateAction('papyrus.act_attachment_form')

    def do_open_(self, action):
        pool = Pool()
        Attachment = pool.get('ir.attachment')
        SaleLine = pool.get('sale.line')
        PurchaseLine = pool.get('purchase.line')
        Invoice = pool.get('account.invoice')
        InvoiceLineStockMove = pool.get('account.invoice.line-stock.move')
        invoice = Invoice(Transaction().context['active_id'])

        resources = set()
        resources.add(str(invoice))
        lines = []
        for line in invoice.lines:
            lines.append(line.id)
            if line.origin:
                if isinstance(line.origin, PurchaseLine):
                    resources.add(str(line.origin.purchase))
                if isinstance(line.origin, SaleLine):
                    resources.add(str(line.origin.sale))

        invoice_stocks = InvoiceLineStockMove.search([
            ('invoice_line', 'in', lines),
            ])

        for invoice_stock in invoice_stocks:
            resources.add(str(invoice_stock.stock_move.shipment))

        domain = ['OR']
        for resource in resources:
            domain.append([('resource', '=', resource)])

        action['pyson_domain'] = PYSONEncoder().encode(domain)
        return action, {}

    def transition_open_(self):
        return 'end'