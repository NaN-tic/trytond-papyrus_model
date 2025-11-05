# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import PoolMeta
from trytond.model import fields
from trytond.pyson import Eval


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('sale', 'Sale'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    sale = fields.One2Many('sale.sale', 'document', "Sale", size=1,
        add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'sale',
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('sale')

    def get_party(self, name):
        if self.model_type == 'sale' and self.sale:
            return self.sale[0].party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party() + [
            ('sale.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'sale': 'Customer sales or sale orders. Take into account that customer documents may refer to them as purchase orders because their purchase is our sale.',
                })
        return types

    def guess_sale(self):
        pass


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'
    document = fields.Many2One('papyrus.document', "Document")

    @classmethod
    def copy(cls, sales, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(sales, default=default)
