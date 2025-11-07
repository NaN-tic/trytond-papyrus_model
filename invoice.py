# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
import json
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder, Eval, Bool, If
from . import tools


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('invoice', 'Supplier Invoice'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    invoice = fields.One2Many('account.invoice', 'document', "Account Invoice",
        size=1, add_remove=[('document', '=', None)],
        context={
            'type': 'in',
            'company': Eval('document_company', -1),
        }, states={
            'invisible': (Eval('model_type') != 'invoice'),
        }, depends=['document_company', 'model_type'])

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('invoice')

    def get_party(self, name):
        if self.model_type == 'invoice' and self.invoice:
            return self.invoice[0].party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party(clause) + [
            ('invoice.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'invoice': 'Supplier invoice',
                })
        return types

    def guess_invoice_messages(self):
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from invoice "
                "documents. Return ONLY JSON (no markdown) valid per the "
                "provided schema. Use numbers for monetary/quantitative "
                "fields; use null when unknown. Extract seller/buyer info "
                "(names, VAT/tax ID, address), document number, dates, "
                "currency, line items (codes, descriptions, quantities, "
                "unit prices, taxes), and totals."
            )
        }
        user = {
            "role": "user",
            "content": [{
                    "type": "text",
                    "text": (
                        "Parse this business document and output STRICT JSON "
                        "matching the schema. No extra text."
                        ),
                    }, {
                    "type": "file",
                    "file": {
                        "filename": self.filename,
                        "file_data": tools.to_url_data(self.data),
                        }
                    }],
            }
        return [system, user]

    def guess_invoice_schema(self):
        return {
            'name': 'invoice',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'invoice_number': {
                        'type': 'string',
                        },
                    'issue_date': {
                        'type': 'string',
                        'description': 'ISO 8601 date (YYYY-MM-DD) if possible.',
                        },
                    'due_date': {
                        'type': 'string',
                        'description': 'ISO 8601 date (YYYY-MM-DD) if present.',
                        },
                    'currency': {
                        'type': 'string',
                        'description': 'ISO 4217 currency code, e.g., EUR, USD.',
                        },
                    'seller': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'},
                            'vat': {'type': 'string'},
                            'address': {'type': 'string'},
                            'email': {'type': 'string'},
                            'phone': {'type': 'string'}
                        },
                        'required': ['name', 'vat', 'address', 'email', 'phone'],
                        'additionalProperties': False
                    },
                    'buyer': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'},
                            'vat': {'type': 'string'},
                            'address': {'type': 'string'},
                            'email': {'type': 'string'},
                            'phone': {'type': 'string'}
                        },
                        'required': ['name', 'vat', 'address', 'email', 'phone'],
                        'additionalProperties': False
                    },
                    'line_items': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'product_code': {'type': 'string'},
                                'description': {'type': 'string'},
                                'quantity': {'type': 'number'},
                                'unit': {'type': 'string'},
                                'unit_price': {'type': 'number'},
                                'discount': {'type': 'number'},
                                'tax_rate': {'type': 'number'},
                                'tax_amount': {'type': 'number'},
                                'line_total_excl_tax': {'type': 'number'},
                                'line_total_incl_tax': {'type': 'number'}
                            },
                            'required': [
                                'product_code', 'description', 'quantity',
                                 'unit', 'unit_price', 'discount',
                                 'tax_rate', 'tax_amount',
                                 'line_total_excl_tax',
                                 'line_total_incl_tax',
                                 ],
                            'additionalProperties': False
                        }
                    },
                    'totals': {
                        'type': 'object',
                        'properties': {
                            'subtotal': {'type': 'number'},
                            'tax': {'type': 'number'},
                            'total': {'type': 'number'},
                        },
                        'required': ['subtotal', 'tax', 'total'],
                        'additionalProperties': False
                    },
                    'notes': {
                        'type': 'string',
                        },
                },
                'required': ['invoice_number', 'issue_date',
                     'due_date', 'currency', 'seller', 'buyer', 'line_items',
                     'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def guess_invoice(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        PapyrusInvoiceLine = pool.get('papyrus.invoice.line')

        if self.model_type != 'invoice':
            return

        if self.extracted_data:
            data = json.loads(self.extracted_data)
        else:
            llms = (self.queue.llms or '').split(' ')
            for llm in llms:
                try:
                    data = tools.llm(
                        messages=self.guess_invoice_messages(),
                        model=llm,
                        pdf_engine=self.queue.llm_pdf_engine,
                        schema=self.guess_invoice_schema())
                except Exception as e:
                    print(f'Error extracting invoice data with {llm}: {e}')
                    continue
                self.extracted_data = json.dumps(data, indent=4)
                self.save()
                break
            else:
                print('All LLMs failed to extract invoice data.')
                return

        if self.invoice:
            invoice = self.invoice[0]
        else:
            invoice = Invoice()
            invoice.document = self
            invoice.type = 'in'
            invoice.on_change_type()
            invoice.company = self.document_company
            invoice.on_change_company()

        if not getattr(invoice, 'party', None):
            invoice.party = self.find_party(data.get('seller', {}))
            if not invoice.party:
                return
            invoice.on_change_party()

        invoice.save()

        if not invoice.reference:
            invoice.reference = data['invoice_number']
        if not invoice.invoice_date:
            invoice.invoice_date = tools.to_date(data['issue_date'])
        if not invoice.papyrus_untaxed_amount:
            invoice.papyrus_untaxed_amount = tools.to_decimal(
                data['totals']['subtotal'])
        if not invoice.papyrus_total_amount:
            invoice.papyrus_total_amount = tools.to_decimal(
                data['totals']['total'])

        lines = []
        for item in data.get('line_items', []):
            line = PapyrusInvoiceLine()
            line.product_code = item.get('product_code')
            line.description = item.get('description')
            line.quantity = tools.to_decimal(item.get('quantity'))
            line.unit_price = tools.to_decimal(item.get('unit_price'))
            line.discount_rate = tools.to_decimal(item.get('discount'))
            if line.discount_rate:
                line.discount_rate = abs(line.discount_rate)
            taxes = item.get('tax_rate')
            if taxes is not None:
                line.taxes = str(taxes)
            line.amount = tools.to_decimal(item.get('line_total_excl_tax'))
            line.product = None
            line.invoice_line = None
            lines.append(line)

        PapyrusInvoiceLine.find_product(invoice.party, lines)
        invoice.papyrus_lines = lines
        self.create_lines_from_papyrus_lines(invoice)
        invoice.save()

    def create_lines_from_papyrus_lines(self, invoice):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')

        digits = InvoiceLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))

        for papyrus_line in invoice.papyrus_lines:
            if papyrus_line.invoice_line:
                continue
            if not papyrus_line.product:
                continue
            line = InvoiceLine()
            line.invoice = invoice
            line.product = papyrus_line.product
            line.on_change_product()
            line.description = papyrus_line.description
            line.quantity = papyrus_line.quantity
            unit_price = papyrus_line.unit_price
            if papyrus_line.discount_rate:
                unit_price *= (Decimal('100')
                    - papyrus_line.discount_rate) / Decimal('100')
            line.unit_price = unit_price.quantize(exp)
            papyrus_line.invoice_line = line

    def find_party(self, data):
        pool = Pool()
        Party = pool.get('party.party')

        if not data:
            return

        vat = data.get('vat')
        if vat:
            vat = vat.replace(' ', '').replace('-', '')
            parties = Party.search([('identifiers.code', '=', vat)], limit=1)
            if parties:
                return parties[0]
            parties = Party.search([('identifiers.code', '=', 'ES' + vat)],
                limit=1)
            if parties:
                return parties[0]

        name = data.get('name')
        if name:
            parties = Party.search([('name', '=', name)])
            if len(parties) == 1:
                return parties[0]
            parties = Party.search([('name', 'ilike', f'%{name}%')])
            if len(parties) == 1:
                return parties[0]


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_untaxed_amount = fields.Numeric('Papyrus Untaxed Amount', states={
            'invisible': ~Bool(Eval('papyrus_untaxed_amount')),
            })
    papyrus_untaxed_amount_matches = fields.Function(fields.Boolean(
            'Papyrus Untaxed Amount Matches', states={
                'invisible': ~Bool(Eval('papyrus_untaxed_amount')),
                }), 'get_papyrus_untaxed_amount_matches')
    papyrus_lines_untaxed_amount = fields.Function(fields.Numeric(
            'Papyrus Lines Untaxed Amount', states={
                'invisible': Bool(Eval('papyrus_untaxed_amount_matches')),
                }), 'get_papyrus_lines_untaxed_amount')
    papyrus_total_amount = fields.Numeric('Papyrus Total Amount', states={
            'invisible': ~Bool(Eval('papyrus_total_amount')),
            })
    papyrus_total_amount_matches = fields.Function(fields.Boolean(
            'Papyrus Total Amount Matches', states={
                'invisible': ~Bool(Eval('papyrus_total_amount')),
                }), 'get_papyrus_total_amount_matches')
    papyrus_lines = fields.One2Many('papyrus.invoice.line', 'invoice',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

    def get_papyrus_untaxed_amount_matches(self, name):
        if not isinstance(self.papyrus_untaxed_amount, Decimal):
            return False
        return self.papyrus_lines_untaxed_amount == self.papyrus_untaxed_amount

    def get_papyrus_total_amount_matches(self, name):
        return False

    def get_papyrus_lines_untaxed_amount(self, name):
        return sum([x.amount for x in self.papyrus_lines if x.amount])

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_modify_exclude.add('document')

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(invoices, default=default)


class PapyrusInvoiceLine(ModelSQL, ModelView):
    __name__ = 'papyrus.invoice.line'

    invoice = fields.Many2One('account.invoice', 'Invoice', required=True,
        ondelete='CASCADE')
    product_code = fields.Char('Product Code')
    description = fields.Text('Description')
    quantity = fields.Numeric('Quantity')
    unit_price = fields.Numeric('Unit Price')
    discount_rate = fields.Numeric('Discount (%)')
    taxes = fields.Char('Taxes')
    amount = fields.Numeric('Amount')
    amount_matches = fields.Function(fields.Boolean('Amount Matches'),
            'get_amount_matches')
    product = fields.Many2One('product.product', 'Product')
    invoice_line = fields.Many2One('account.invoice.line', 'Invoice Line',
        ondelete='SET NULL')
    invoice_line_matches = fields.Function(fields.Boolean('Invoice Line Matches'),
            'get_invoice_line_matches')

    def get_amount_matches(self, name):
        if (not isinstance(self.quantity, Decimal)
                or not isinstance(self.unit_price, Decimal)
                or not isinstance(self.amount, Decimal)):
            return False
        unit_price = self.unit_price
        if self.discount_rate:
            unit_price *= (Decimal('100') - self.discount_rate) / Decimal('100')
        amount = self.quantity * unit_price
        return self.amount == amount

    def get_invoice_line_matches(self, name):
        if not self.invoice_line:
            return False
        matches = True
        if self.quantity is not None:
            matches &= self.invoice_line.quantity == self.quantity
        if self.unit_price is not None:
            matches &= self.invoice_line.unit_price == self.unit_price
        return matches

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name="amount"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name="invoice_line"]',
                'visual', If(Eval('invoice_line_matches', False), 'success', 'danger')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        pool = Pool()
        Product = pool.get('product.product')
        try:
            ProductSupplier = pool.get('purchase.product_supplier')
        except KeyError:
            ProductSupplier = None

        to_search = []
        for line in lines:
            if line.product_code:
                to_search.append(line.product_code)
            if line.description:
                to_search.append(line.description)
        products = Product.search([('code', 'in', to_search)])
        by_code = {x.code: x for x in products}
        products = Product.search([('name', 'in', to_search)])
        by_name = {x.name: x for x in products}

        if ProductSupplier:
            psuppliers = ProductSupplier.search([
                    ('party', '=', party),
                    ('code', 'in', to_search),
                    ])
            for psupplier in psuppliers:
                if psupplier.code:
                    if psupplier.product:
                        by_code[psupplier.code] = psupplier.product
                    elif psupplier.template.products:
                        by_code[psupplier.code] = psupplier.template.products[0]
            psuppliers = ProductSupplier.search([
                    ('party', '=', party),
                    ('name', 'in', to_search),
                    ])
            for psupplier in psuppliers:
                if psupplier.name:
                    if psupplier.product:
                        by_name[psupplier.name] = psupplier.product
                    elif psupplier.template.products:
                        by_name[psupplier.name] = psupplier.template.products[0]

        for line in lines:
            product = None
            if line.product_code:
                product = by_code.get(line.product_code)
            if not product and line.description:
                product = by_name.get(line.description)
            if not product and line.description:
                product = by_code.get(line.description)
            if not product and line.product_code:
                product = by_name.get(line.product_code)
            if product:
                line.product = product
                continue

            psuppliers = ProductSupplier.search([
                    ('party', '=', party),
                    ('code', 'ilike', line.product_code),
                    ], limit=1)
            if psuppliers:
                psupplier, = psuppliers
                if psupplier.product:
                    line.product = psupplier.product
                elif psupplier.template.products:
                    line.product = psupplier.template.products[0]
                continue

            ps = Product.search([('code', 'ilike', line.product_code)],
                limit=1)
            if ps:
                line.product, = ps
                continue


class InvoiceDossier(Wizard):
    __name__ = 'invoice.dossier'

    start_state = 'open_'
    open_ = StateAction('papyrus.act_attachment_form')

    def do_open_(self, action):
        pool = Pool()

        try:
            SaleLine = pool.get('sale.line')
        except KeyError:
            SaleLine = None
        try:
            PurchaseLine = pool.get('purchase.line')
        except KeyError:
            PurchaseLine = None
        try:
            InvoiceLineStockMove = pool.get('account.invoice.line-stock.move')
        except KeyError:
            InvoiceLineStockMove = None

        invoice = self.record

        resources = set()
        resources.add(str(invoice))
        lines = []
        for line in invoice.lines:
            lines.append(line.id)
            if line.origin:
                if PurchaseLine and isinstance(line.origin, PurchaseLine):
                    resources.add(str(line.origin.purchase))
                if SaleLine and isinstance(line.origin, SaleLine):
                    resources.add(str(line.origin.sale))

        if InvoiceLineStockMove:
            invoice_stocks = InvoiceLineStockMove.search([
                ('invoice_line', 'in', lines),
                ])
            for invoice_stock in invoice_stocks:
                shipment = invoice_stock.stock_move.shipment
                if shipment:
                    resources.add(str(shipment))

        sub_domain = []
        for resource in resources:
            sub_domain.append(resource)

        domain = [('resource', 'in', sub_domain)]
        action['pyson_domain'] = PYSONEncoder().encode(domain)
        return action, {}

    def transition_open_(self):
        return 'end'
