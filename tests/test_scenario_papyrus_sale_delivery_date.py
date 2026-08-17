from datetime import date
from decimal import Decimal

from trytond.modules.company.tests import create_company, set_company
from trytond.modules.papyrus_model.tests.test_module import PapyrusModelTestCase
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class Test(PapyrusModelTestCase):

    extras = PapyrusModelTestCase.extras + ['sale_delivery_date']

    @with_transaction()
    def test(self):
        PapyrusSaleLine = Pool().get('papyrus.sale.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Customer')
            product = self._create_product('PM-DELIVERY-DATE')
            sale = self._create_sale(company, party)
            papyrus_line = PapyrusSaleLine(
                sale=sale,
                product=product,
                quantity=Decimal(1),
                unit_price=Decimal('10.00'),
                delivery_date=date(2026, 9, 30),
                )

            sale_line = papyrus_line.get_sale_line()
            self.assertEqual(sale_line.manual_delivery_date,
                date(2026, 9, 30))
