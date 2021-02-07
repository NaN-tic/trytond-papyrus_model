# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import document
from . import invoice
from . import sale
from . import stock

module = 'papyrus_model'

def register():
    Pool.register(
        document.DocumentBox,
        document.Queue,
        document.Document,
        document.Value,
        invoice.Invoice,
        sale.Sale,
        stock.ShipmentIn,
        module=module, type_='model')
    Pool.register(
        invoice.InvoiceDossier,
        module=module, type_='wizard')
