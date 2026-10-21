from datetime import date
from decimal import Decimal

from trytond.modules.company.tests import create_company, set_company
from trytond.modules.papyrus_model.tests.test_module import (
    PapyrusModelTestCase)
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class Test(PapyrusModelTestCase):

    @with_transaction()
    def test(self):
        PurchaseLine = Pool().get('purchase.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Delivery Supplier')
            product = self._create_product('PM-DESIRED-DATE')
            purchase = self._create_purchase(company, party)
            line = self._create_purchase_line(
                purchase, product, Decimal('10'), Decimal('10'))
            PurchaseLine.write([line], {
                    'delivery_date_edit': True,
                    'delivery_date_store': date(2026, 9, 15),
                    })
            PurchaseLine.write([line], {'desired_delivery_date': None})

            PurchaseLine.write([line], {
                    'delivery_date_store': date(2026, 9, 30),
                    })

            line = PurchaseLine(line.id)
            self.assertEqual(
                line.desired_delivery_date, date(2026, 9, 15))
            self.assertEqual(line.delivery_date_store, date(2026, 9, 30))
