# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import document
from . import invoice
from . import sale
from . import stock


def register():
    module = 'papyrus_model'
    Pool.register(
        document.Queue,
        document.Document,
        module=module, type_='model')
    Pool.register(
        invoice.Queue,
        invoice.Document,
        invoice.Invoice,
        invoice.PapyrusInvoiceLine,
        module=module, type_='model', depends=['account_invoice'])
    Pool.register(
        invoice.InvoiceDossier,
        module=module, type_='wizard', depends=['account_invoice'])
    Pool.register(
        stock.Queue,
        stock.Document,
        stock.ShipmentIn,
        module=module, type_='model', depends=['stock'])
    Pool.register(
        sale.Queue,
        sale.Document,
        sale.Sale,
        module=module, type_='model', depends=['sale'])
