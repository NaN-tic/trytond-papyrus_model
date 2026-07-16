# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import json
from datetime import date, timedelta
from decimal import Decimal
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.pyson import Eval, Bool, If
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.transaction import Transaction
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
        cls._check_model_exists.add('sale')

    def get_party(self, name):
        if self.model_type == 'sale' and self.sale:
            Party = Pool().get('party.party')
            party = self.sale[0].party
            if Party.search([('id', '=', party.id)], limit=1):
                return party.id
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
                "taxes, line totals), and totals. If a line contains both "
                "our/internal product code and the customer's product code, "
                "keep them separate: product_code is our/internal code and "
                "party_product_code is the customer code. Return in "
                "unit_price the price of exactly one billed unit. If the "
                "document has a separate price-base column, often labeled "
                "Unidad Precio or shown as values like (100), (10), (1), box, "
                "pack, etc., copy that value into unit and use it to "
                "normalize unit_price to one unit. Never invent or guess a "
                "quantity base that is not clearly written in the document. "
                "quantity must be the real number of billed units, and line "
                "totals must stay as the full line totals from the document. "
                "When the document shows withholdings such as IRPF, treat "
                "them as tax/withholding adjustments instead of product or "
                "service line items. Do not create a separate line item only "
                "for the withholding; reflect it through taxes, totals, or "
                "notes when needed."
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
                    }],
            }
        if self.data is not None:
            user["content"].append({
                    "type": "file",
                    "file": {
                        "filename": self.filename,
                        "file_data": tools.to_url_data(self.data),
                        }
                    })
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
                            'vat': {'type': ['string', 'null']},
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
                            'vat': {'type': ['string', 'null']},
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
                                'product_code': {'type': ['string', 'null']},
                                'party_product_code': {
                                    'type': ['string', 'null']},
                                'description': {'type': 'string'},
                                'quantity': {'type': 'number'},
                                'unit': {
                                    'type': 'string',
                                    'description': ('Unit of measure or the '
                                        'explicit price-base shown in the '
                                        'document, such as (100), (10), (1), '
                                        'box or pack.'),
                                    },
                                'unit_price': {
                                    'type': 'number',
                                    'description': ('Net unit price for one '
                                        'billed unit. If the document shows '
                                        'the price for an explicit base '
                                        'quantity such as (100), (10), (1), '
                                        'per box or per pack, normalize it to '
                                        'one unit and keep that explicit base '
                                        'in unit.'),
                                    },
                                'discount': {'type': 'number'},
                                'tax_rate': {'type': 'number'},
                                'tax_amount': {'type': 'number'},
                                'line_total_excl_tax': {'type': 'number'},
                                'line_total_incl_tax': {'type': 'number'}
                            },
                            'required': [
                                'product_code', 'party_product_code',
                                 'description', 'quantity',
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
        Currency = pool.get('currency.currency')
        Sale = pool.get('sale.sale')
        PapyrusSaleLine = pool.get('papyrus.sale.line')

        if self.model_type != 'sale':
            return

        messages = self.guess_sale_messages()
        schema = self.guess_sale_schema()
        data = self.extract_data_with_llm('sale', messages, schema)
        if not data:
            return

        if self.sale:
            sale = self.sale[0]
        else:
            sale = Sale()
            sale.document = self
            sale.company = self.document_company
            sale.on_change_company()

        if (getattr(sale, 'papyrus_lines', None)
                and not Transaction().context.get('papyrus_reinspect')):
            sale.papyrus_lines = []
            sale.save()

        if not getattr(sale, 'party', None):
            buyer = data.get('buyer', {})
            sale.party = self.find_sale_party_from_data(buyer, data)
            if not sale.party:
                tools.logger.warning(
                    'Document %s extracted sale data but no '
                    'customer party was matched; skipping sale creation '
                    '(buyer_name=%s, buyer_vat=%s)',
                    self.id, buyer.get('name'), buyer.get('vat'))
                return
            sale.on_change_party()

        currency_code = (data.get('currency') or '').upper()
        if currency_code:
            currencies = Currency.search([('code', '=', currency_code)],
                limit=1)
            if currencies:
                sale.currency, = currencies

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
        buyer = data.get('buyer', {})
        buyer_name = (buyer.get('name') or '').strip().upper()
        if buyer_name:
            sale.papyrus_name = buyer_name

        lines = getattr(sale, 'papyrus_lines', None)
        if not lines:
            lines = []
            for item in data.get('line_items', []):
                line = PapyrusSaleLine()
                line.set_from_data(item)
                lines.append(line)
            sale.papyrus_lines = lines
        PapyrusSaleLine.find_product(sale.party, lines)
        sale.create_sale_lines_from_papyrus_lines()
        sale.save()

    def find_sale_party_from_data(self, data, extracted_data=None):
        Party = Pool().get('party.party')
        role_domain = [('customer', '=', True)] if 'customer' in Party._fields else []

        if not data:
            return

        vat = data.get('vat')
        if vat:
            normalized_vat = ''.join(char for char in vat if char.isalnum())
            normalized_vat = normalized_vat.upper()
            for code in (normalized_vat,
                    (not normalized_vat.startswith('ES')
                        and 'ES' + normalized_vat) or None):
                if not code:
                    continue
                parties = Party.search([
                        ('identifiers.code', '=', code),
                        ] + role_domain,
                    limit=1)
                if parties:
                    return parties[0]

        name = (data.get('name') or '').strip().upper()
        if not name:
            return
        issue_date = tools.to_date(
            extracted_data and extracted_data.get('issue_date'))
        cutoff = (issue_date or date.today()) - timedelta(days=730)
        papyrus_party, papyrus_similarity = tools.find_party_by_similarity(
            name, model_name='sale.sale', role_field='customer',
            related_party_field='party', related_date_field='sale_date',
            cutoff=cutoff)
        if papyrus_similarity == 1:
            return papyrus_party

        party, party_similarity = tools.find_party_by_similarity(name,
            role_domain)
        if party_similarity == 1:
            return party
        if papyrus_similarity >= party_similarity:
            return papyrus_party
        return party

class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_name = fields.Char('Papyrus Name')
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
        Document = Pool().get('papyrus.document')
        return Document.amounts_match(
            self.papyrus_lines_untaxed_amount, self.papyrus_untaxed_amount)

    def get_papyrus_total_amount_matches(self, name):
        return False

    def get_papyrus_lines_untaxed_amount(self, name):
        return sum([x.amount for x in getattr(self, 'papyrus_lines', [])
                if x.amount])

    def create_sale_lines_from_papyrus_lines(self):
        SaleLine = Pool().get('sale.line')

        to_save = []
        papyrus_lines = []
        for papyrus_line in getattr(self, 'papyrus_lines', []):
            if getattr(papyrus_line, 'sale_line', None):
                continue
            sale_line = papyrus_line.get_sale_line()
            if not sale_line:
                continue
            to_save.append(sale_line)
            papyrus_lines.append(papyrus_line)

        if to_save:
            SaleLine.save(to_save)
            for papyrus_line, sale_line in zip(papyrus_lines, to_save):
                papyrus_line.sale_line = sale_line

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'create_lines': {
                    'invisible': ~Bool(Eval('papyrus_lines')),
                    'depends': ['papyrus_lines'],
                    },
                })

    @classmethod
    @ModelView.button
    def create_lines(cls, sales):
        for sale in sales:
            pending = [line for line in getattr(sale, 'papyrus_lines', [])
                if (not getattr(line, 'sale_line', None)
                    and not getattr(line, 'product', None))]
            if pending:
                raise UserError(gettext('papyrus_model.'
                        'msg_cannot_create_lines_with_unmatched_products',
                        document=sale.rec_name,
                        total=len(pending)))

            if not sale.document:
                continue

            sale.create_sale_lines_from_papyrus_lines()
            sale.save()

    @classmethod
    def copy(cls, sales, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(sales, default=default)

    @classmethod
    def create(cls, vlist):
        sales = super().create(vlist)
        for sale in sales:
            if not sale.document:
                continue
            if not sale.document.extracted_data:
                continue
            try:
                data = json.loads(sale.document.extracted_data)
            except (TypeError, ValueError):
                continue
            buyer = data.get('buyer') or {}
            name = (buyer.get('name') or '').strip().upper()
            if not name:
                continue
            if sale.papyrus_name == name:
                continue
            sale.papyrus_name = name
            sale.save()
        return sales

    @classmethod
    def write(cls, *args):
        super().write(*args)
        actions = iter(args)
        for sales, values in zip(actions, actions):
            if 'party' not in values:
                continue
            for sale in sales:
                if not sale.party or not sale.document:
                    continue
                if not sale.document.extracted_data:
                    continue
                try:
                    data = json.loads(sale.document.extracted_data)
                except (TypeError, ValueError):
                    continue
                buyer = data.get('buyer') or {}
                name = (buyer.get('name') or '').strip().upper()
                if not name:
                    continue
                if sale.papyrus_name == name:
                    continue
                super().write([sale], {'papyrus_name': name})


class PapyrusSaleLine(ModelSQL, ModelView):
    __name__ = 'papyrus.sale.line'

    sale = fields.Many2One('sale.sale', 'Sale', required=True,
        ondelete='CASCADE')
    product_code = fields.Char('Product Code')
    external_code = fields.Char('External Code')
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

    def set_from_data(self, data):
        product_code = data.get('product_code')
        if isinstance(product_code, str):
            product_code = product_code.replace('\x00', '').strip() or None
        external_code = data.get('party_product_code')
        if isinstance(external_code, str):
            external_code = external_code.replace('\x00', '').strip() or None
        description = data.get('description')
        if isinstance(description, str):
            description = description.replace('\x00', '').strip()
        self.product_code = product_code
        self.external_code = external_code
        self.description = description
        self.quantity = tools.to_decimal(data.get('quantity'))
        self.unit_price = tools.to_decimal(data.get('unit_price'))
        self.discount_rate = tools.to_decimal(data.get('discount'))
        self.amount = tools.to_decimal(data.get('line_total_excl_tax'))
        if self.discount_rate:
            self.discount_rate = abs(self.discount_rate)
        taxes = data.get('tax_rate')
        if taxes is not None:
            self.taxes = str(taxes)

    def get_sale_line(self):
        SaleLine = Pool().get('sale.line')

        sale = self.sale
        product = getattr(self, 'product', None)
        unit_price = getattr(self, 'unit_price', None)
        if not product or unit_price is None:
            return
        digits = SaleLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))
        sale_line = SaleLine()
        sale_line.sale = sale
        sale_line.product = product
        sale_line.on_change_product()
        sale_line.description = getattr(self, 'description', None)
        sale_line.quantity = getattr(self, 'quantity', None)
        sale_line.on_change_quantity()
        discount_rate = getattr(self, 'discount_rate', None)
        if discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        sale_line.unit_price = unit_price.quantize(exp)
        return sale_line

    def get_amount_matches(self, name):
        Document = Pool().get('papyrus.document')
        quantity = getattr(self, 'quantity', None)
        unit_price = getattr(self, 'unit_price', None)
        amount = getattr(self, 'amount', None)
        if (not isinstance(quantity, Decimal)
                or not isinstance(unit_price, Decimal)
                or not isinstance(amount, Decimal)):
            return False
        discount_rate = getattr(self, 'discount_rate', None)
        if discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        return Document.amounts_match(amount, quantity * unit_price)

    def get_sale_line_matches(self, name):
        Document = Pool().get('papyrus.document')
        sale_line = getattr(self, 'sale_line', None)
        if not sale_line:
            return False
        quantity = getattr(self, 'quantity', None)
        if quantity is not None and sale_line.quantity != quantity:
            return False
        unit_price = getattr(self, 'unit_price', None)
        if (unit_price is not None
                and not Document.amounts_match(sale_line.unit_price,
                    unit_price)):
            return False
        product = getattr(self, 'product', None)
        if product is not None and sale_line.product != product:
            return False
        return True

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name=\"amount\"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name=\"sale_line\"]',
                'visual', If(Bool(Eval('sale_line')),
                    If(Eval('sale_line_matches', False),
                        'success', 'danger'), '')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        lines = [line for line in lines if not line.product]
        if not lines:
            return
        pool = Pool()
        Product = pool.get('product.product')
        HistoryLine = pool.get('papyrus.sale.line')
        try:
            ProductCustomer = pool.get('sale.product_customer')
        except KeyError:
            ProductCustomer = None

        values = []
        for line in lines:
            description = getattr(line, 'description', None)
            product_code = getattr(line, 'product_code', None)
            external_code = getattr(line, 'external_code', None)
            if isinstance(description, str):
                description = description.replace('\x00', '').strip() or None
                line.description = description
            if isinstance(product_code, str):
                product_code = product_code.replace('\x00', '').strip() or None
                line.product_code = product_code
            if isinstance(external_code, str):
                external_code = external_code.replace('\x00', '').strip() or None
                line.external_code = external_code
            if product_code:
                values.append(product_code)
            if external_code:
                values.append(external_code)
            if description:
                values.append(description)

        by_code = {}
        by_name = {}
        history_by_code = {}
        history_by_description = {}
        products_by_code = Product.search([('code', 'in', values)])
        for product in products_by_code:
            if product.code:
                by_code[product.code] = product
        products_by_name = Product.search([('name', 'in', values)])
        for product in products_by_name:
            if product.name:
                by_name[product.name] = product

        if ProductCustomer:
            pcustomers_by_code = ProductCustomer.search([
                    ('party', '=', party),
                    ('code', 'in', values),
                    ])
            for record in pcustomers_by_code:
                product = (record.product or
                    (record.template.products and record.template.products[0]))
                if record.code and product:
                    by_code[record.code] = product
            pcustomers_by_name = ProductCustomer.search([
                    ('party', '=', party),
                    ('name', 'in', values),
                    ])
            for record in pcustomers_by_name:
                product = (record.product or
                    (record.template.products and record.template.products[0]))
                if record.name and product:
                    by_name[record.name] = product
        history_codes = list({
                getattr(line, 'product_code', None)
                for line in lines if getattr(line, 'product_code', None)})
        history_lookup_codes = list({
                getattr(line, 'external_code', None)
                for line in lines if getattr(line, 'external_code', None)})
        history_descriptions = list({
                getattr(line, 'description', None)
                for line in lines if getattr(line, 'description', None)})
        if history_codes or history_lookup_codes or history_descriptions:
            history_domain = [('sale.party', '=', party),
                ('product', '!=', None)]
            code_values = list(dict.fromkeys(history_codes + history_lookup_codes))
            if code_values and history_descriptions:
                history_domain.append(['OR',
                        ('product_code', 'in', code_values),
                        ('description', 'in', history_descriptions),
                        ])
            elif code_values:
                history_domain.append(('product_code', 'in', code_values))
            else:
                history_domain.append(('description', 'in',
                        history_descriptions))
            history_lines = HistoryLine.search(history_domain,
                order=[('id', 'DESC')])
            for line in history_lines:
                product = getattr(line, 'product', None)
                if line.product_code and product:
                    history_by_code.setdefault(line.product_code, product)
                if line.description and product:
                    history_by_description.setdefault(line.description,
                        product)

        for line in lines:
            description = getattr(line, 'description', None)
            product_code = getattr(line, 'product_code', None)
            external_code = getattr(line, 'external_code', None)
            product = None
            if product_code:
                product = by_code.get(product_code)
            if not product and external_code:
                product = by_code.get(external_code)
            if not product and description:
                product = by_name.get(description)
            if not product and description:
                product = by_code.get(description)
            if not product and product_code:
                product = by_name.get(product_code)
            if not product and external_code:
                product = by_name.get(external_code)
            if not product and product_code:
                product = history_by_code.get(product_code)
            if not product and external_code:
                product = history_by_code.get(external_code)
            if not product and description:
                product = history_by_description.get(description)
            if product:
                line.product = product
                continue

            if ProductCustomer and product_code:
                records = ProductCustomer.search([
                        ('party', '=', party),
                        ('code', 'ilike', product_code),
                        ], limit=1)
                if records:
                    record, = records
                    if record.product:
                        line.product = record.product
                    elif record.template.products:
                        line.product = record.template.products[0]
                if getattr(line, 'product', None):
                    continue
            if ProductCustomer and external_code:
                records = ProductCustomer.search([
                        ('party', '=', party),
                        ('code', 'ilike', external_code),
                        ], limit=1)
                if records:
                    record, = records
                    if record.product:
                        line.product = record.product
                    elif record.template.products:
                        line.product = record.template.products[0]
                if getattr(line, 'product', None):
                    continue

            if product_code:
                products = Product.search([('code', 'ilike', product_code)],
                    limit=1)
                if products:
                    line.product, = products
                    continue
            if external_code:
                products = Product.search([('code', 'ilike', external_code)],
                    limit=1)
                if products:
                    line.product, = products
