# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import document
from . import invoice
from . import sale
from . import purchase
from . import stock


def register():
    module = 'papyrus_model'
    Pool.register(
        document.Queue,
        document.Document,
        module=module, type_='model')
    Pool.register(
        invoice.Party,
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
        stock.PapyrusShipmentInLine,
        module=module, type_='model', depends=['stock'])
    Pool.register(
        sale.Queue,
        sale.Configuration,
        sale.Document,
        sale.Sale,
        sale.SaleLine,
        sale.SalePreviousSale,
        sale.PapyrusSaleLine,
        module=module, type_='model', depends=['sale'])
    Pool.register(
        purchase.Queue,
        purchase.Document,
        purchase.Purchase,
        purchase.PurchaseLine,
        purchase.PapyrusPurchaseLine,
        module=module, type_='model', depends=['purchase'])
