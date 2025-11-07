# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
import json
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.pyson import Eval, Bool, If
from . import tools


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
        add_remove=[('document', '=', None)], context={
            'company': Eval('document_company', -1),
            }, states={
            'invisible': (Eval('model_type') != 'sale'),
            }, depends=['document_company', 'model_type'])

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
        return super()._search_party(clause) + [
            ('sale.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'sale': ('Customer sales or sale orders. Take into account '
                    'that customer documents may refer to them as purchase '
                    'orders because their purchase is our sale.'),
                })
        return types

    def guess_sale_messages(self):
        info = self.get_company_info()
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from sale "
                f"order documents where the seller is {info}. Return ONLY JSON "
                "(no markdown) valid per the provided schema. Use numbers for "
                "monetary/quantitative fields; use null when unknown. Extract "
                "seller/buyer info (names, VAT/tax ID, address, email, "
                "phone), document number, dates, currency, line items "
                "(codes, descriptions, quantities, unit prices, discounts, "
                "taxes, line totals), and totals."
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

    def guess_sale_schema(self):
        return {
            'name': 'sale',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'sale_number': {
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
                'required': ['sale_number', 'issue_date',
                     'due_date', 'currency', 'seller', 'buyer', 'line_items',
                     'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def guess_sale(self):
        pool = Pool()
        Sale = pool.get('sale.sale')
        PapyrusSaleLine = pool.get('papyrus.sale.line')

        if self.model_type != 'sale':
            return

        if self.extracted_data:
            data = json.loads(self.extracted_data)
        else:
            llms = (self.queue.llms or '').split(' ')
            for llm in llms:
                try:
                    data = tools.llm(
                        messages=self.guess_sale_messages(),
                        model=llm,
                        pdf_engine=self.queue.llm_pdf_engine,
                        schema=self.guess_sale_schema())
                except Exception as e:
                    print(f'Error extracting sale data with {llm}: {e}')
                    continue
                self.extracted_data = json.dumps(data, indent=4)
                self.save()
                break
            else:
                print('All LLMs failed to extract sale data.')
                return

        if self.sale:
            sale = self.sale[0]
        else:
            sale = Sale()
            sale.document = self
            sale.company = self.document_company
            sale.on_change_company()

        if not getattr(sale, 'party', None):
            sale.party = self.find_party(data.get('buyer', {}))
            if not sale.party:
                return
            sale.on_change_party()

        sale.save()

        if not sale.reference:
            sale.reference = data['sale_number']
        if not sale.sale_date:
            sale.sale_date = tools.to_date(data['issue_date'])
        if not sale.papyrus_untaxed_amount:
            sale.papyrus_untaxed_amount = tools.to_decimal(
                data['totals']['subtotal'])
        if not sale.papyrus_total_amount:
            sale.papyrus_total_amount = tools.to_decimal(
                data['totals']['total'])

        lines = []
        for item in data.get('line_items', []):
            line = PapyrusSaleLine()
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
            line.sale_line = None
            lines.append(line)

        PapyrusSaleLine.find_product(sale.party, lines)
        sale.papyrus_lines = lines
        self.create_lines_from_papyrus_lines(sale)
        sale.save()

    def create_lines_from_papyrus_lines(self, sale):
        pool = Pool()
        SaleLine = pool.get('sale.line')

        digits = SaleLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))

        for papyrus_line in sale.papyrus_lines:
            if papyrus_line.sale_line:
                continue
            if not papyrus_line.product:
                continue
            line = SaleLine()
            line.sale = sale
            line.product = papyrus_line.product
            line.on_change_product()
            line.description = papyrus_line.description
            line.quantity = papyrus_line.quantity
            line.on_change_quantity()
            unit_price = papyrus_line.unit_price
            if papyrus_line.discount_rate:
                unit_price *= (Decimal('100')
                    - papyrus_line.discount_rate) / Decimal('100')
            line.unit_price = unit_price.quantize(exp)
            papyrus_line.sale_line = line

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


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'
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
    papyrus_lines = fields.One2Many('papyrus.sale.line', 'sale',
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
    def copy(cls, sales, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(sales, default=default)


class PapyrusSaleLine(ModelSQL, ModelView):
    __name__ = 'papyrus.sale.line'

    sale = fields.Many2One('sale.sale', 'Sale', required=True,
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
    sale_line = fields.Many2One('sale.line', 'Sale Line',
        ondelete='SET NULL')
    sale_line_matches = fields.Function(fields.Boolean('Sale Line Matches'),
            'get_sale_line_matches')

    def get_amount_matches(self, name):
        if (not isinstance(self.quantity, Decimal)
                or not isinstance(self.unit_price, Decimal)
                or not isinstance(self.amount, Decimal)):
            return False
        unit_price = self.unit_price
        if self.discount_rate:
            unit_price *= (Decimal('100') - self.discount_rate) / Decimal('100')
        amount = self.quantity * unit_price
        exp = Decimal('0.01')
        return self.amount.quantize(exp) == amount.quantize(exp)

    def get_sale_line_matches(self, name):
        if not self.sale_line:
            return False
        matches = True
        if self.quantity is not None:
            matches &= self.sale_line.quantity == self.quantity
        if self.unit_price is not None:
            matches &= self.sale_line.unit_price == self.unit_price
        return matches

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name=\"amount\"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name=\"sale_line\"]',
                'visual', If(Eval('sale_line_matches', False), 'success', 'danger')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        pool = Pool()
        Product = pool.get('product.product')

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

            ps = Product.search([('code', 'ilike', line.product_code)],
                limit=1)
            if ps:
                line.product, = ps
                continue
