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
            ('purchase', 'Purchase'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    purchase = fields.One2Many('purchase.purchase', 'document', "Purchase", size=1,
        add_remove=[('document', '=', None)], context={
            'company': Eval('document_company', -1),
            }, depends=['document_company', 'model_type'],
        states={
            'invisible': Eval('model_type') != 'purchase',
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('purchase')
        cls._check_model_exists.add('purchase')

    def get_party(self, name):
        if self.model_type == 'purchase' and self.purchase:
            Party = Pool().get('party.party')
            party = self.purchase[0].party
            if Party.search([('id', '=', party.id)], limit=1):
                return party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party(clause) + [
            ('purchase.party',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'purchase': 'Supplier confirmation of a purchase',
                })
        return types

    def guess_purchase_messages(self):
        info = self.get_company_info()
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from purchase "
                "confirmation documents where the seller is the supplier and "
                f"the buyer is {info}. Return ONLY JSON (no markdown) valid "
                "per the provided schema. Use numbers for "
                "monetary/quantitative fields; use null when unknown. Extract "
                "seller/buyer info (names, VAT/tax ID, address, email, "
                "phone), document number, dates, currency, line items "
                "(codes, descriptions, quantities, unit prices, discounts, "
                "taxes, line totals), and totals. If a line contains both "
                "our/internal product code and the supplier's product code, "
                "keep them separate: product_code is our/internal code and "
                "party_product_code is the supplier code. Return in "
                "unit_price the price of exactly one billed unit. If the "
                "document has a separate price-base column, often labeled "
                "Unidad Precio or shown as values like (100), (10), (1), box, "
                "pack, etc., copy that value into unit and use it to "
                "normalize unit_price to one unit. Never invent or guess a "
                "quantity base that is not clearly written in the document. "
                "quantity must be the real number of billed units, and line "
                "totals must stay as the full line totals from the document."
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

    def guess_purchase_schema(self):
        return {
            'name': 'purchase',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'purchase_number': {
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
                'required': ['purchase_number', 'issue_date',
                    'due_date', 'currency', 'seller', 'buyer', 'line_items',
                    'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def guess_purchase(self):
        pool = Pool()
        Currency = pool.get('currency.currency')
        Purchase = pool.get('purchase.purchase')
        PapyrusPurchaseLine = pool.get('papyrus.purchase.line')

        if self.model_type != 'purchase':
            return

        messages = self.guess_purchase_messages()
        schema = self.guess_purchase_schema()
        data = self.extract_data_with_llm('purchase', messages, schema)
        if not data:
            return

        if self.purchase:
            purchase = self.purchase[0]
        else:
            purchase = Purchase()
            purchase.document = self
            purchase.company = self.document_company
            purchase.on_change_company()

        if (getattr(purchase, 'papyrus_lines', None)
                and Transaction().context.get('papyrus_reinspect')):
            purchase.papyrus_lines = []
            purchase.save()

        if not getattr(purchase, 'party', None):
            seller = data.get('seller', {})
            purchase.party = self.find_purchase_party_from_data(seller, data)
            if not purchase.party:
                tools.logger.warning(
                    'Document %s extracted purchase data but no '
                    'supplier party was matched; skipping purchase creation '
                    '(seller_name=%s, seller_vat=%s)',
                    self.id, seller.get('name'), seller.get('vat'))
                return
            purchase.on_change_party()

        currency_code = (data.get('currency') or '').upper()
        if currency_code:
            currencies = Currency.search([('code', '=', currency_code)],
                limit=1)
            if currencies:
                purchase.currency, = currencies

        if not getattr(purchase, 'warehouse', None):
            if getattr(self.document_company, 'purchase_warehouse', None):
                purchase.warehouse = self.document_company.purchase_warehouse
            elif getattr(self.document_company, 'warehouse', None):
                purchase.warehouse = self.document_company.warehouse

        purchase.save()

        if not purchase.reference:
            purchase.reference = data['purchase_number']
        if not purchase.purchase_date:
            purchase.purchase_date = tools.to_date(data['issue_date'])
        seller = data.get('seller', {})
        seller_name = (seller.get('name') or '').strip().upper()
        if seller_name:
            purchase.papyrus_name = seller_name

        lines = []
        for item in data.get('line_items', []):
            product_code = item.get('product_code')
            if isinstance(product_code, str):
                product_code = product_code.replace('\x00', '').strip() or None
            external_code = item.get('party_product_code')
            if isinstance(external_code, str):
                external_code = external_code.replace('\x00', '').strip() or None
            description = item.get('description')
            if isinstance(description, str):
                description = description.replace('\x00', '').strip()
            line = PapyrusPurchaseLine()
            line.product_code = product_code
            line.external_code = external_code
            line.description = description
            line.quantity = tools.to_decimal(item.get('quantity'))
            line.unit_price = tools.to_decimal(item.get('unit_price'))
            line.discount_rate = tools.to_decimal(item.get('discount'))
            line.amount = tools.to_decimal(item.get('line_total_excl_tax'))
            if line.discount_rate:
                line.discount_rate = abs(line.discount_rate)
            taxes = item.get('tax_rate')
            if taxes is not None:
                line.taxes = str(taxes)
            lines.append(line)
        PapyrusPurchaseLine.find_product(purchase.party, lines)
        purchase.papyrus_lines = lines
        self.create_purchase_lines_from_papyrus_lines(purchase)
        purchase.save()

    def find_purchase_party_from_data(self, data, extracted_data=None):
        Party = Pool().get('party.party')
        role_domain = [('supplier', '=', True)] if 'supplier' in Party._fields else []

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
            name, model_name='purchase.purchase', role_field='supplier',
            related_party_field='party', related_date_field='purchase_date',
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

    def create_purchase_lines_from_papyrus_lines(self, purchase):
        pool = Pool()
        PurchaseLine = pool.get('purchase.line')

        digits = PurchaseLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))

        to_save = []
        papyrus_lines = []

        for papyrus_line in getattr(purchase, 'papyrus_lines', []):
            if getattr(papyrus_line, 'purchase_line', None):
                continue
            product = getattr(papyrus_line, 'product', None)
            if not product:
                continue
            line = PurchaseLine()
            line.purchase = purchase
            line.product = product
            line.on_change_product()
            line.description = getattr(papyrus_line, 'description', None)
            line.quantity = getattr(papyrus_line, 'quantity', None)
            line.on_change_quantity()
            unit_price = getattr(papyrus_line, 'unit_price', None)
            if unit_price is None:
                continue
            discount_rate = getattr(papyrus_line, 'discount_rate', None)
            if discount_rate:
                unit_price *= (Decimal('100')
                    - discount_rate) / Decimal('100')
            line.unit_price = unit_price.quantize(exp)
            line.on_change_taxes()
            to_save.append(line)
            papyrus_lines.append(papyrus_line)

        if to_save:
            PurchaseLine.save(to_save)
            for papyrus_line, line in zip(papyrus_lines, to_save):
                papyrus_line.purchase_line = line


class Purchase(metaclass=PoolMeta):
    __name__ = 'purchase.purchase'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_name = fields.Char('Papyrus Name')
    papyrus_lines = fields.One2Many('papyrus.purchase.line', 'purchase',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

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
    def create_lines(cls, purchases):
        for purchase in purchases:
            pending = [line for line in getattr(purchase, 'papyrus_lines', [])
                if (not getattr(line, 'purchase_line', None)
                    and not getattr(line, 'product', None))]
            if pending:
                raise UserError(gettext('papyrus_model.'
                        'msg_cannot_create_lines_with_unmatched_products',
                        document=purchase.rec_name,
                        total=len(pending)))

            if not purchase.document:
                continue

            purchase.document.create_purchase_lines_from_papyrus_lines(
                purchase)
            purchase.save()

    @classmethod
    def copy(cls, purchases, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(purchases, default=default)

    @classmethod
    def create(cls, vlist):
        purchases = super().create(vlist)
        for purchase in purchases:
            if not purchase.document:
                continue
            if not purchase.document.extracted_data:
                continue
            try:
                data = json.loads(purchase.document.extracted_data)
            except (TypeError, ValueError):
                continue
            seller = data.get('seller') or {}
            name = (seller.get('name') or '').strip().upper()
            if not name:
                continue
            if purchase.papyrus_name == name:
                continue
            purchase.papyrus_name = name
            purchase.save()
        return purchases

    @classmethod
    def write(cls, *args):
        super().write(*args)
        actions = iter(args)
        for purchases, values in zip(actions, actions):
            if 'party' not in values:
                continue
            for purchase in purchases:
                if not purchase.party or not purchase.document:
                    continue
                if not purchase.document.extracted_data:
                    continue
                try:
                    data = json.loads(purchase.document.extracted_data)
                except (TypeError, ValueError):
                    continue
                seller = data.get('seller') or {}
                name = (seller.get('name') or '').strip().upper()
                if not name:
                    continue
                if purchase.papyrus_name == name:
                    continue
                super().write([purchase], {'papyrus_name': name})


class PapyrusPurchaseLine(ModelSQL, ModelView):
    __name__ = 'papyrus.purchase.line'

    purchase = fields.Many2One('purchase.purchase', 'Purchase', required=True,
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
    purchase_line = fields.Many2One('purchase.line', 'Purchase Line',
        ondelete='SET NULL')
    purchase_line_matches = fields.Function(
        fields.Boolean('Purchase Line Matches'), 'get_purchase_line_matches')

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

    def get_purchase_line_matches(self, name):
        Document = Pool().get('papyrus.document')
        purchase_line = getattr(self, 'purchase_line', None)
        if not purchase_line:
            return False
        quantity = getattr(self, 'quantity', None)
        if quantity is not None and purchase_line.quantity != quantity:
            return False
        unit_price = getattr(self, 'unit_price', None)
        if (unit_price is not None
                and not Document.amounts_match(purchase_line.unit_price,
                    unit_price)):
            return False
        product = getattr(self, 'product', None)
        if product is not None and purchase_line.product != product:
            return False
        return True

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name="amount"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name="purchase_line"]',
                'visual', If(Bool(Eval('purchase_line')),
                    If(Eval('purchase_line_matches', False),
                        'success', 'danger'), '')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        pool = Pool()
        Product = pool.get('product.product')
        HistoryLine = pool.get('papyrus.purchase.line')
        try:
            ProductSupplier = pool.get('purchase.product_supplier')
        except KeyError:
            ProductSupplier = None

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

        if ProductSupplier:
            psuppliers_by_code = ProductSupplier.search([
                    ('party', '=', party),
                    ('code', 'in', values),
                    ])
            for record in psuppliers_by_code:
                product = (record.product or
                    (record.template.products and record.template.products[0]))
                if record.code and product:
                    by_code[record.code] = product
            psuppliers_by_name = ProductSupplier.search([
                    ('party', '=', party),
                    ('name', 'in', values),
                    ])
            for record in psuppliers_by_name:
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
            history_domain = [('purchase.party', '=', party),
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

            if ProductSupplier and product_code:
                records = ProductSupplier.search([
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
            if ProductSupplier and external_code:
                records = ProductSupplier.search([
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
