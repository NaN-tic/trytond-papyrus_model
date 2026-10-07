import unittest
from decimal import Decimal

from proteus import Model, config
from trytond.modules.account.tests.tools import create_chart, get_accounts
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestProductCodes(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules([
                'papyrus_model', 'purchase', 'sale', 'stock',
                'account_invoice', 'sale_product_customer'])
        create_company()
        company = get_company()
        create_chart(company)
        accounts = get_accounts(company)
        Category = Model.get('product.category')
        category = Category(name='Category', accounting=True,
            account_expense=accounts['expense'],
            account_revenue=accounts['revenue'])
        category.save()
        Party = Model.get('party.party')
        party = Party(name='Party', account_payable=accounts['payable'],
            account_receivable=accounts['receivable'])
        party.save()
        other_party = Party(name='Other Party')
        other_party.save()
        Company = Model.get('company.company')
        other_company = Company(party=other_party, currency=company.currency)
        other_company.save()
        User = Model.get('res.user')
        user = User(config.get_config().user)
        user.companies.append(other_company)
        user.company_filter = 'all'
        user.save()
        with config.get_config().set_context(
                company=other_company.id, companies=[other_company.id]):
            create_chart(other_company)
            other_accounts = get_accounts(other_company)
        Uom = Model.get('product.uom')
        unit, = Uom.find([('name', '=', 'Unit')])
        Template = Model.get('product.template')
        products = {}
        for code in ('AB-12.34', 'CL-01', 'CL01', 'HISTORY-1',
                'MATCH-40.01'):
            template = Template(name=code, code=code, type='goods',
                default_uom=unit, purchase_uom=unit, sale_uom=unit,
                account_category=category, purchasable=True, salable=True)
            template.save()
            products[code], = template.products
        product = products['AB-12.34']
        Supplier = Model.get('purchase.product_supplier')
        Customer = Model.get('sale.product_customer')
        for Related in (Supplier, Customer):
            record = Related(party=party, product=product,
                template=product.template, code='EXT-90 01')
            record.save()
            record = Related(party=other_party,
                product=products['HISTORY-1'],
                template=products['HISTORY-1'].template, code='EXT9001')
            record.save()
            for code, target in (
                    ('MATCH-40.01', products['HISTORY-1']),):
                record = Related(party=party, product=target,
                    template=target.template, code=code)
                record.save()
        Location = Model.get('stock.location')
        warehouse, = Location.find([('type', '=', 'warehouse')])
        parents = (
            ('papyrus.purchase.line', Model.get('purchase.purchase')(
                    party=party, warehouse=warehouse)),
            ('papyrus.sale.line', Model.get('sale.sale')(party=party)),
            ('papyrus.invoice.line', Model.get('account.invoice')(
                    party=party, type='in')),
            ('papyrus.shipment.in.line', Model.get('stock.shipment.in')(
                    supplier=party, warehouse=warehouse)),
            )
        for _, parent in parents:
            parent.papyrus_lines.new(product=products['HISTORY-1'],
                product_code='PAST-77 03', quantity=Decimal('1'))
            parent.save()

        configuration = config.get_config()
        currency_id = company.currency.id
        other_payable_id = other_accounts['payable'].id
        history_template_id = products['HISTORY-1'].template.id
        with Transaction().start(configuration.database_name,
                configuration.user, context=configuration.context):
            pool = Pool()
            BackendProduct = pool.get('product.product')
            ProductSupplier = pool.get('purchase.product_supplier')
            ProductSupplier.create([{
                        'party': party.id,
                        'template': history_template_id,
                        'product': products['HISTORY-1'].id,
                        'company': other_company.id,
                        'currency': currency_id,
                        'code': 'REMOTE-88 02'}])
            for model_name, parent in parents:
                Line = pool.get(model_name)
                Parent = pool.get(parent.__class__.__name__)
                defaults = {
                        'company': other_company.id,
                        'papyrus_lines.product_code': 'OTHER-55 01',
                        'papyrus_lines.description': 'Other company item'}
                if model_name == 'papyrus.invoice.line':
                    defaults['account'] = other_payable_id
                Parent.copy([Parent(parent.id)], defaults)
                for code in ('ab 12-34', 'AB1234', 'AB_12/34',
                        'AB\u00a012–34'):
                    line = Line.build({'product_code': code, 'quantity': 1})
                    Line.find_product(party.id, [line])
                    self.assertEqual(line.product.id, product.id)
                    self.assertEqual(line.product_code, code)
                line = Line.build({'party_product_code': 'ext 9001',
                        'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, product.id)
                line = Line.build({'product_code': 'PAST7703', 'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, products['HISTORY-1'].id)
                for code in ('REMOTE8802', 'REMOTE-88 02'):
                    line = Line.build({'product_code': code, 'quantity': 1})
                    Line.find_product(party.id, [line])
                    if model_name == 'papyrus.sale.line':
                        self.assertIsNone(getattr(line, 'product', None))
                    else:
                        self.assertEqual(line.product.id,
                            products['HISTORY-1'].id)
                for code in ('OTHER5501', 'OTHER-55 01'):
                    line = Line.build({'product_code': code, 'quantity': 1})
                    Line.find_product(party.id, [line])
                    self.assertEqual(line.product.id, products['HISTORY-1'].id)
                line = Line.build({'description': 'Other company item',
                        'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, products['HISTORY-1'].id)
                for field in ('product_code', 'party_product_code'):
                    for code in ('MATCH-40.01', 'MATCH4001', 'match 40/01'):
                        line = Line.build({field: code, 'quantity': 1})
                        Line.find_product(party.id, [line])
                        self.assertEqual(line.product.id,
                            products['HISTORY-1'].id)
                    for code in ('CL 01',):
                        line = Line.build({field: code, 'quantity': 1})
                        Line.find_product(party.id, [line])
                        self.assertIsNone(getattr(line, 'product', None))
                    for code in ('CL_01', 'CL%01'):
                        line = Line.build({field: code, 'quantity': 1})
                        Line.find_product(party.id, [line])
                        self.assertIn(line.product.id,
                            [products['CL-01'].id, products['CL01'].id])
                line = Line.build({'product_code': 'AB1234',
                    'description': 'HISTORY-1', 'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, products['HISTORY-1'].id)
                line = Line.build({'product_code': 'CL01', 'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, products['CL01'].id)
                line = Line.build({'product_code': 'NO-MATCH', 'quantity': 1})
                Line.find_product(party.id, [line])
                self.assertIsNone(getattr(line, 'product', None))
                line.product = BackendProduct(products['HISTORY-1'].id)
                Line.find_product(party.id, [line])
                self.assertEqual(line.product.id, products['HISTORY-1'].id)

            ShipmentLine = pool.get('papyrus.shipment.in.line')
            Move = pool.get('stock.move')
            move = Move(product=product.id, unit_price=Decimal('12.5'))
            unvalued = ShipmentLine.build({'quantity': 1})
            self.assertIsNone(unvalued.unit_price)
            unvalued.product = move.product
            self.assertEqual(unvalued.get_line_candidates([move]), [move])
            valued = ShipmentLine.build({'quantity': 1, 'unit_price': 12.5})
            self.assertEqual(valued.unit_price, Decimal('12.500000'))
            valued.product = move.product
            self.assertEqual(valued.get_line_candidates([move]), [move])
            move.unit_price = Decimal('10')
            self.assertEqual(valued.get_line_candidates([move]), [])
            free = ShipmentLine.build({'quantity': 1, 'unit_price': 0})
            self.assertEqual(free.unit_price, Decimal('0.000000'))
