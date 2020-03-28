# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields
from trytond.config import config as config_


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
    document = fields.Many2One('papyrus.document', "Document")
