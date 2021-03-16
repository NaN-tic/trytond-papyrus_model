# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
    document = fields.Many2One('papyrus.document', "Document")

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._check_modify_exclude += ['document']

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super(Invoice, cls).copy(invoices, default=default)
