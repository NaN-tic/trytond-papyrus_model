# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from datetime import date, timedelta
from decimal import Decimal
from trytond.modules.company.tests import create_company, set_company
from trytond.modules.account.tests import create_chart, get_fiscalyear
from trytond.modules.account_invoice.tests import set_invoice_sequences
from trytond.modules.papyrus.tests import PapyrusCompanyTestMixin
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction


class PapyrusModelTestCase(PapyrusCompanyTestMixin, ModuleTestCase):
    'Test PapyrusModel module'
    module = 'papyrus_model'
    extras = ['account_invoice', 'purchase', 'sale', 'stock']

    def _create_product(self, code, name='Papyrus Product'):
        pool = Pool()
        Company = pool.get('company.company')
        Product = pool.get('product.product')
        Template = pool.get('product.template')
        Uom = pool.get('product.uom')

        if Transaction().context.get('company'):
            self._ensure_chart(Company(Transaction().context['company']))

        uom, = Uom.search([], limit=1)

        defaults = Template.default_get(list(Template._fields.keys()),
            with_rec_name=False)
        template = Template(**defaults)
        template.name = name
        if 'code' in Template._fields:
            template.code = code
        template.default_uom = uom
        if 'account_category' in Template._fields:
            template.account_category = self._get_account_category()
        if 'sale_uom' in Template._fields:
            template.sale_uom = uom
        if 'purchase_uom' in Template._fields:
            template.purchase_uom = uom
        if 'salable' in Template._fields:
            template.salable = True
        if 'purchasable' in Template._fields:
            template.purchasable = True
        template.save()

        product, = Product.search([
                ('template', '=', template.id),
                ], limit=1)
        return product

    def _get_account_category(self):
        pool = Pool()
        Account = pool.get('account.account')
        Category = pool.get('product.category')
        Company = pool.get('company.company')

        company_id = Company(Transaction().context['company']).id
        categories = Category.search([
                ('accounting', '=', True),
                ], limit=1)
        if categories:
            return categories[0]

        expense, = Account.search([
                ('type.expense', '=', True),
                ('closed', '!=', True),
                ('company', '=', company_id),
                ], limit=1)
        revenue, = Account.search([
                ('type.revenue', '=', True),
                ('closed', '!=', True),
                ('company', '=', company_id),
                ], limit=1)
        category = Category(name='Papyrus Account Category', accounting=True)
        if 'account_expense' in Category._fields:
            category.account_expense = expense
        if 'account_revenue' in Category._fields:
            category.account_revenue = revenue
        category.save()
        return category

    def _ensure_chart(self, company):
        pool = Pool()
        Account = pool.get('account.account')

        accounts = Account.search([
                ('closed', '!=', True),
                ('company', '=', company.id),
                ], limit=1)
        if not accounts:
            create_chart(company)

    def _create_party(self, company, name='Party'):
        pool = Pool()
        Account = pool.get('account.account')
        Party = pool.get('party.party')

        self._ensure_chart(company)
        receivable, = Account.search([
                ('type.receivable', '=', True),
                ('closed', '!=', True),
                ('company', '=', company.id),
                ], limit=1)
        payable, = Account.search([
                ('type.payable', '=', True),
                ('closed', '!=', True),
                ('company', '=', company.id),
                ], limit=1)
        party, = Party.create([{
                    'name': name,
                    'account_receivable': receivable.id,
                    'account_payable': payable.id,
                    'addresses': [('create', [{}])],
                    }])
        if 'customer' in Party._fields:
            party.customer = True
        if 'supplier' in Party._fields:
            party.supplier = True
        party.save()
        return party

    def _assert_find_product_by_code(self, model_name, code):
        Line = Pool().get(model_name)

        company = create_company()
        with set_company(company):
            product = self._create_product(code)
            line = Line()
            line.product_code = code

            Line.find_product(company.party, [line])
            self.assertEqual(line.product, product)

    def _assert_find_product_by_ean(self, model_name):
        Identifier = Pool().get('product.identifier')
        Line = Pool().get(model_name)

        company = create_company()
        with set_company(company):
            product = self._create_product('%s-EAN' % model_name)
            identifier = Identifier()
            identifier.product = product
            identifier.type = 'ean'
            identifier.code = '4006381333931'
            identifier.save()

            line = Line()
            line.ean = '4006381333931'
            Line.find_product(company.party, [line])
            self.assertEqual(line.product, product)

    def _assert_find_party_by_papyrus_name(self, method_name, data,
            parent_factory, date_field):
        Document = Pool().get('papyrus.document')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Official Name')
            record = parent_factory(company, party)
            record.papyrus_name = data['name'].upper()
            setattr(record, date_field, date.today())
            record.save()

            document = Document()
            found = getattr(document, method_name)(data)
            self.assertEqual(found, party)

    def _assert_find_party_by_name(self, method_name, data):
        Document = Pool().get('papyrus.document')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Official Name')

            document = Document()
            found = getattr(document, method_name)(data)
            self.assertEqual(found, party)

    def _create_purchase(self, company, party):
        Purchase = Pool().get('purchase.purchase')

        purchase = Purchase()
        purchase.company = company
        purchase.on_change_company()
        purchase.party = party
        purchase.on_change_party()
        purchase.invoice_method = 'fulfillment'
        purchase.save()
        return purchase

    def _create_sale(self, company, party):
        Sale = Pool().get('sale.sale')

        sale = Sale()
        sale.company = company
        sale.on_change_company()
        sale.party = party
        sale.on_change_party()
        sale.save()
        return sale

    def _create_shipment_in(self, company, party):
        pool = Pool()
        Location = pool.get('stock.location')
        ShipmentIn = pool.get('stock.shipment.in')

        warehouse, = Location.search([
                ('type', '=', 'warehouse'),
                ], limit=1)
        shipment = ShipmentIn()
        shipment.company = company
        shipment.supplier = party
        shipment.on_change_supplier()
        shipment.warehouse = warehouse
        shipment.on_change_warehouse()
        shipment.save()
        return shipment

    def _create_supplier_invoice(self, company, party):
        pool = Pool()
        Account = pool.get('account.account')
        Address = pool.get('party.address')
        FiscalYear = pool.get('account.fiscalyear')
        Invoice = pool.get('account.invoice')

        self._ensure_chart(company)
        fiscalyear = set_invoice_sequences(get_fiscalyear(company))
        fiscalyear.save()
        FiscalYear.create_period([fiscalyear])

        if not party.id:
            party.save()

        payable, = Account.search([
                ('type.payable', '=', True),
                ('closed', '!=', True),
                ('company', '=', company.id),
                ], limit=1)
        address, = Address.create([{
                    'party': party.id,
                    }])
        party.account_payable = payable
        party.save()

        invoice = Invoice()
        invoice.type = 'in'
        invoice.company = company
        invoice.party = party
        invoice.on_change_type()
        invoice.on_change_party()
        invoice.invoice_address = address
        invoice.save()
        return invoice

    def _create_product_supplier(self, company, party, product, code,
            name='Supplier Product'):
        ProductSupplier = Pool().get('purchase.product_supplier')

        record = ProductSupplier()
        record.party = party
        record.product = product
        record.template = product.template
        record.company = company
        record.code = code
        record.name = name
        record.save()
        return record

    def _create_purchase_line(self, purchase, product, quantity, unit_price,
            product_supplier=None, description='Test line'):
        PurchaseLine = Pool().get('purchase.line')

        line = PurchaseLine()
        line.purchase = purchase
        line.type = 'line'
        line.product = product
        line.on_change_product()
        line.description = description
        line.quantity = quantity
        if product_supplier:
            line.product_supplier = product_supplier
        line.on_change_quantity()
        line.unit_price = unit_price
        line.save()
        return line

    def _create_pending_invoice_line_from_purchase_line(self, purchase_line):
        InvoiceLine = Pool().get('account.invoice.line')

        invoice_line, = purchase_line.get_invoice_line()
        if 'party' in InvoiceLine._fields:
            invoice_line.party = purchase_line.purchase.party
        InvoiceLine.save([invoice_line])
        return invoice_line

    def _create_shipment_move(self, shipment, product, quantity, origin):
        Move = Pool().get('stock.move')

        move = Move()
        move.shipment = shipment
        move.product = product
        move.on_change_product()
        move.quantity = quantity
        move.from_location = shipment.supplier.supplier_location
        move.to_location = shipment.warehouse.input_location
        move.company = shipment.company
        move.currency = shipment.company.currency
        move.unit_price = Decimal('0.0000')
        move.origin = origin
        move.save()
        return move

    def _assert_find_product_from_previous_papyrus_line(
            self, model_name, parent_factory, line_field, history_code,
            history_field='product_code'):
        Line = Pool().get(model_name)

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='%s Party' % model_name)
            parent = parent_factory(company, party)
            product = self._create_product('%s-PRODUCT' % history_code)

            previous = Line(**{line_field: parent})
            setattr(previous, history_field, history_code)
            previous.product = product
            previous.save()

            line = Line()
            setattr(line, history_field, history_code)

            Line.find_product(party, [line])
            self.assertEqual(line.product, product)

    def _assert_find_product_from_previous_description(
            self, model_name, parent_factory, line_field, description):
        Line = Pool().get(model_name)

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='%s Party' % model_name)
            parent = parent_factory(company, party)
            product = self._create_product('%s-PRODUCT' % model_name)

            previous = Line(**{line_field: parent})
            previous.description = description
            previous.product = product
            previous.save()

            line = Line()
            line.description = description

            Line.find_product(party, [line])
            self.assertEqual(line.product, product)

    def _assert_find_product_from_external_code_matches_previous_product_code(
            self, model_name, parent_factory, line_field, code):
        Line = Pool().get(model_name)

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='%s Party' % model_name)
            parent = parent_factory(company, party)
            product = self._create_product('%s-PRODUCT' % code)

            previous = Line(**{line_field: parent})
            previous.product_code = code
            previous.product = product
            previous.save()

            line = Line()
            line.external_code = code

            Line.find_product(party, [line])
            self.assertEqual(line.product, product)

    @with_transaction()
    def test_guess_company_from_buyer_vat(self):
        Document = Pool().get('papyrus.document')
        Identifier = Pool().get('party.identifier')

        company = create_company()
        identifier = Identifier()
        identifier.party = company.party
        identifier.type = 'eu_vat'
        identifier.code = 'ESB64836372'
        identifier.save()

        document = Document()
        document.guess_company({
                'buyer': {
                    'name': 'Dama Electronic',
                    'vat': 'B64836372',
                    },
                })

        self.assertEqual(document.company, company)
        self.assertEqual(document.guessed_company, company)

    @with_transaction()
    def test_default_sale_quotation_validity(self):
        Configuration = Pool().get('sale.configuration')

        company = create_company()
        with set_company(company):
            configuration = Configuration(1)
            self.assertEqual(
                configuration.get_multivalue(
                    'sale_quotation_validity', company=company.id),
                timedelta(weeks=1))

    @with_transaction()
    def test_invoice_line_find_product_by_code(self):
        self._assert_find_product_by_code('papyrus.invoice.line',
            'PM-INV-001')

    @with_transaction()
    def test_invoice_line_find_product_by_ean(self):
        self._assert_find_product_by_ean('papyrus.invoice.line')

    @with_transaction()
    def test_invoice_party_find_by_papyrus_name(self):
        self._assert_find_party_by_papyrus_name(
            'find_invoice_party_from_data', {
                'name': 'Papyrus Supplier Alias',
                'vat': None,
                }, self._create_supplier_invoice, 'invoice_date')

    @with_transaction()
    def test_invoice_party_find_by_uppercase_name(self):
        self._assert_find_party_by_name(
            'find_invoice_party_from_data', {
                'name': 'OFFICIAL NAME',
                'vat': None,
                })

    @with_transaction()
    def test_sale_line_find_product_by_code(self):
        self._assert_find_product_by_code('papyrus.sale.line',
            'PM-SALE-001')

    @with_transaction()
    def test_sale_line_find_product_by_ean(self):
        self._assert_find_product_by_ean('papyrus.sale.line')

    @with_transaction()
    def test_sale_links_explicit_previous_quotation(self):
        Sale = Pool().get('sale.sale')

        company = create_company()
        with set_company(company):
            party = self._create_party(company)
            previous = self._create_sale(company, party)
            Sale.quote([previous])

            sale = self._create_sale(company, party)
            sale.previous_sale_reference = previous.number
            sale.save()
            sale.link_previous_sales()

            self.assertEqual(sale.previous_sales, (previous,))

    @with_transaction()
    def test_sale_party_find_by_papyrus_name(self):
        self._assert_find_party_by_papyrus_name(
            'find_sale_party_from_data', {
                'name': 'Papyrus Customer Alias',
                'vat': None,
                }, self._create_sale, 'sale_date')

    @with_transaction()
    def test_shipment_line_find_product_by_code(self):
        self._assert_find_product_by_code('papyrus.shipment.in.line',
            'PM-SHIP-001')

    @with_transaction()
    def test_shipment_line_find_product_by_ean(self):
        self._assert_find_product_by_ean('papyrus.shipment.in.line')

    @with_transaction()
    def test_shipment_party_find_by_papyrus_name(self):
        self._assert_find_party_by_papyrus_name(
            'find_shipment_in_party_from_data', {
                'name': 'Papyrus Shipment Supplier Alias',
                'vat': None,
                }, self._create_shipment_in, 'effective_date')

    @with_transaction()
    def test_purchase_line_find_product_by_code(self):
        self._assert_find_product_by_code('papyrus.purchase.line',
            'PM-PUR-001')

    @with_transaction()
    def test_purchase_line_find_product_by_ean(self):
        self._assert_find_product_by_ean('papyrus.purchase.line')

    @with_transaction()
    def test_purchase_party_find_by_papyrus_name(self):
        self._assert_find_party_by_papyrus_name(
            'find_purchase_party_from_data', {
                'name': 'Papyrus Purchase Supplier Alias',
                'vat': None,
                }, self._create_purchase, 'purchase_date')

    @with_transaction()
    def test_invoice_line_find_product_from_previous_papyrus_line(self):
        self._assert_find_product_from_previous_papyrus_line(
            'papyrus.invoice.line', self._create_supplier_invoice,
            'invoice', 'SUPPLIER-001')

    @with_transaction()
    def test_invoice_line_find_product_from_previous_description(self):
        self._assert_find_product_from_previous_description(
            'papyrus.invoice.line', self._create_supplier_invoice,
            'invoice', 'Invoice Description Match')

    @with_transaction()
    def test_invoice_line_find_product_from_external_code_matches_previous_product_code(self):
        self._assert_find_product_from_external_code_matches_previous_product_code(
            'papyrus.invoice.line', self._create_supplier_invoice,
            'invoice', 'SUPPLIER-SWAPPED-001')

    @with_transaction()
    def test_invoice_line_find_product_prefers_latest_previous_match(self):
        Line = Pool().get('papyrus.invoice.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Supplier')
            invoice = self._create_supplier_invoice(company, party)
            old_product = self._create_product('PM-HISTORY-OLD')
            new_product = self._create_product('PM-HISTORY-NEW')

            old_line = Line(invoice=invoice)
            old_line.product_code = 'SUPPLIER-RECENT-001'
            old_line.product = old_product
            old_line.save()

            new_line = Line(invoice=invoice)
            new_line.product_code = 'SUPPLIER-RECENT-001'
            new_line.product = new_product
            new_line.save()

            line = Line()
            line.product_code = 'SUPPLIER-RECENT-001'

            Line.find_product(party, [line])
            self.assertEqual(line.product, new_product)

    @with_transaction()
    def test_invoice_line_find_invoice_line_prefers_our_order_number(self):
        PapyrusInvoiceLine = Pool().get('papyrus.invoice.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Supplier')
            product = self._create_product('PM-WORKFLOW-ORDER')

            purchase1 = self._create_purchase(company, party)
            purchase1.number = 'PO-KEEP'
            purchase1.reference = 'SUP-REF-1'
            purchase1.invoice_method = 'order'
            purchase1.save()
            purchase2 = self._create_purchase(company, party)
            purchase2.number = 'PO-OTHER'
            purchase2.reference = 'SUP-REF-2'
            purchase2.invoice_method = 'order'
            purchase2.save()

            line1 = self._create_purchase_line(
                purchase1, product, 5, Decimal('10.0000'))
            line2 = self._create_purchase_line(
                purchase2, product, 5, Decimal('10.0000'))
            invoice_line1 = self._create_pending_invoice_line_from_purchase_line(
                line1)
            self._create_pending_invoice_line_from_purchase_line(line2)

            papyrus_line = PapyrusInvoiceLine()
            papyrus_line.product = product
            papyrus_line.quantity = Decimal('5')
            papyrus_line.unit_price = Decimal('10.0000')

            PapyrusInvoiceLine.find_invoice_line(party, [papyrus_line], {
                    'issue_date': date.today().isoformat(),
                    'our_order_number': 'PO-KEEP',
                    'party_order_number': None,
                    'party_shipment_number': None,
                    })
            self.assertEqual(papyrus_line.invoice_line, invoice_line1)

    @with_transaction()
    def test_invoice_line_find_invoice_line_prefers_party_shipment_number(self):
        PapyrusInvoiceLine = Pool().get('papyrus.invoice.line')
        InvoiceLine = Pool().get('account.invoice.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Supplier')
            product = self._create_product('PM-WORKFLOW-SHIPMENT')

            purchase1 = self._create_purchase(company, party)
            purchase1.invoice_method = 'order'
            purchase1.save()
            purchase2 = self._create_purchase(company, party)
            purchase2.invoice_method = 'order'
            purchase2.save()

            line1 = self._create_purchase_line(
                purchase1, product, 5, Decimal('10.0000'))
            line2 = self._create_purchase_line(
                purchase2, product, 5, Decimal('10.0000'))
            invoice_line1 = self._create_pending_invoice_line_from_purchase_line(
                line1)
            invoice_line2 = self._create_pending_invoice_line_from_purchase_line(
                line2)

            shipment1 = self._create_shipment_in(company, party)
            shipment1.reference = 'ALB-KEEP'
            shipment1.effective_date = date.today()
            shipment1.save()
            shipment2 = self._create_shipment_in(company, party)
            shipment2.reference = 'ALB-OTHER'
            shipment2.effective_date = date.today()
            shipment2.save()

            move1 = self._create_shipment_move(shipment1, product, 5, line1)
            move2 = self._create_shipment_move(shipment2, product, 5, line2)
            invoice_line1.stock_moves = [move1]
            invoice_line2.stock_moves = [move2]
            InvoiceLine.save([invoice_line1, invoice_line2])

            papyrus_line = PapyrusInvoiceLine()
            papyrus_line.product = product
            papyrus_line.quantity = Decimal('5')
            papyrus_line.unit_price = Decimal('10.0000')

            PapyrusInvoiceLine.find_invoice_line(party, [papyrus_line], {
                    'issue_date': date.today().isoformat(),
                    'our_order_number': None,
                    'party_order_number': None,
                    'party_shipment_number': 'ALB-KEEP',
                    })
            self.assertEqual(papyrus_line.invoice_line, invoice_line1)

    @with_transaction()
    def test_invoice_line_find_invoice_line_matches_external_code(self):
        PapyrusInvoiceLine = Pool().get('papyrus.invoice.line')

        company = create_company()
        with set_company(company):
            party = self._create_party(company, name='Supplier')
            product = self._create_product('PM-WORKFLOW-EXT')

            purchase1 = self._create_purchase(company, party)
            purchase1.number = 'PO-EXT-1'
            purchase1.invoice_method = 'order'
            purchase1.save()
            purchase2 = self._create_purchase(company, party)
            purchase2.number = 'PO-EXT-2'
            purchase2.invoice_method = 'order'
            purchase2.save()

            ps1 = self._create_product_supplier(
                company, party, product, 'EXT-KEEP')
            ps2 = self._create_product_supplier(
                company, party, product, 'EXT-OTHER')
            line1 = self._create_purchase_line(
                purchase1, product, 5, Decimal('10.0000'),
                product_supplier=ps1)
            line2 = self._create_purchase_line(
                purchase2, product, 5, Decimal('10.0000'),
                product_supplier=ps2)
            invoice_line1 = self._create_pending_invoice_line_from_purchase_line(
                line1)
            self._create_pending_invoice_line_from_purchase_line(line2)

            papyrus_line = PapyrusInvoiceLine()
            papyrus_line.quantity = Decimal('5')
            papyrus_line.unit_price = Decimal('10.0000')
            papyrus_line.external_code = 'EXT-KEEP'

            PapyrusInvoiceLine.find_invoice_line(party, [papyrus_line], {
                    'issue_date': date.today().isoformat(),
                    'our_order_number': None,
                    'party_order_number': None,
                    'party_shipment_number': None,
                    })
            self.assertEqual(papyrus_line.invoice_line, invoice_line1)

    @with_transaction()
    def test_purchase_line_find_product_from_previous_papyrus_line(self):
        self._assert_find_product_from_previous_papyrus_line(
            'papyrus.purchase.line', self._create_purchase,
            'purchase', 'SUPPLIER-PUR-001')

    @with_transaction()
    def test_purchase_line_find_product_from_previous_description(self):
        self._assert_find_product_from_previous_description(
            'papyrus.purchase.line', self._create_purchase,
            'purchase', 'Purchase Description Match')

    @with_transaction()
    def test_purchase_line_find_product_from_external_code_matches_previous_product_code(self):
        self._assert_find_product_from_external_code_matches_previous_product_code(
            'papyrus.purchase.line', self._create_purchase,
            'purchase', 'SUPPLIER-PUR-SWAPPED-001')

    @with_transaction()
    def test_sale_line_find_product_from_previous_papyrus_line(self):
        self._assert_find_product_from_previous_papyrus_line(
            'papyrus.sale.line', self._create_sale,
            'sale', 'CUSTOMER-SALE-001')

    @with_transaction()
    def test_sale_line_find_product_from_previous_description(self):
        self._assert_find_product_from_previous_description(
            'papyrus.sale.line', self._create_sale,
            'sale', 'Sale Description Match')

    @with_transaction()
    def test_sale_line_find_product_from_external_code_matches_previous_product_code(self):
        self._assert_find_product_from_external_code_matches_previous_product_code(
            'papyrus.sale.line', self._create_sale,
            'sale', 'CUSTOMER-SALE-SWAPPED-001')

    @with_transaction()
    def test_shipment_line_find_product_from_previous_papyrus_line(self):
        self._assert_find_product_from_previous_papyrus_line(
            'papyrus.shipment.in.line', self._create_shipment_in,
            'shipment', 'SUPPLIER-SHIP-001')

    @with_transaction()
    def test_shipment_line_find_product_from_previous_description(self):
        self._assert_find_product_from_previous_description(
            'papyrus.shipment.in.line', self._create_shipment_in,
            'shipment', 'Shipment Description Match')

    @with_transaction()
    def test_shipment_line_find_product_from_external_code_matches_previous_product_code(self):
        self._assert_find_product_from_external_code_matches_previous_product_code(
            'papyrus.shipment.in.line', self._create_shipment_in,
            'shipment', 'SUPPLIER-SHIP-SWAPPED-001')

    @with_transaction()
    def test_sale_party_find_by_name_ignores_non_customer(self):
        Document = Pool().get('papyrus.document')
        Party = Pool().get('party.party')

        company = create_company()
        with set_company(company):
            if 'customer' not in Party._fields:
                return
            party = self._create_party(company, name='ROLE FILTER PARTY')
            party.customer = False
            party.supplier = True
            party.save()

            document = Document()
            found = document.find_sale_party_from_data({
                    'name': 'ROLE FILTER PARTY',
                    'vat': None,
                    })
            self.assertIsNone(found)

    @with_transaction()
    def test_amounts_match_accepts_one_cent_margin(self):
        Document = Pool().get('papyrus.document')

        self.assertTrue(Document.amounts_match(Decimal('10.00'),
                Decimal('10.01')))
        self.assertFalse(Document.amounts_match(Decimal('10.00'),
                Decimal('10.02')))

del ModuleTestCase
