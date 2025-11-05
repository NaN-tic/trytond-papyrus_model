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
            ('purchase', 'Purchase'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    purchase = fields.One2Many('purchase.purchase', 'document', "Purchase", size=1,
        add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'purchase',
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('purchase')

    def get_party(self, name):
        if self.model_type == 'purchase' and self.purchase:
            return self.purchase[0].party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party() + [
            ('purchase.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'purchase': 'Supplier confirmation of a purchase',
                })
        return types

    def guess_purchase(self):
        pass


class Purchase(metaclass=PoolMeta):
    __name__ = 'purchase.purchase'
    document = fields.Many2One('papyrus.document', "Document")

    @classmethod
    def copy(cls, purchases, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(purchases, default=default)

