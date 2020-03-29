# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'
    document = fields.Many2One('papyrus.document', "Document")
