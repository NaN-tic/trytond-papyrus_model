# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import json
from datetime import date, timedelta
from decimal import Decimal
from stdnum import ean
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.pyson import Eval, Bool, If
from trytond.exceptions import UserError, UserWarning
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
                "phone), document number, our purchase number, supplier "
                "purchase reference, dates, currency, line items "
                "(codes, EANs, descriptions, quantities, unit prices, discounts, "
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
                "quantity must be the real number of billed units. For a "
                "quantity/date split, report the amount for that split and "
                "make all split quantities and amounts add up to the full "
                "line totals from the document. "
                "When the document shows withholdings such as IRPF, treat "
                "them as tax/withholding adjustments instead of product or "
                "service line items. Do not create a separate line item only "
                "for the withholding; reflect it through taxes, totals, or "
                "notes when needed. If both purchase numbers are present, "
                "purchase_number is our purchase/order number and "
                "purchase_reference is the supplier's purchase/order "
                "reference. If unsure, return the closest values in those "
                "fields. When a supplier confirms different quantities of "
                "the same product for different delivery dates, return one "
                "line item for each quantity/date split. Repeat the product "
                "and pricing data on each split. Do not merge dates or invent "
                "dates."
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
                        'type': ['string', 'null'],
                        },
                    'purchase_reference': {
                        'type': ['string', 'null'],
                        },
                    'issue_date': {
                        'type': 'string',
                        'description': 'ISO 8601 date (YYYY-MM-DD) if possible.',
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
                                'ean': {'type': ['string', 'null']},
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
                                'line_total_incl_tax': {'type': 'number'},
                                'delivery_date': {
                                    'type': ['string', 'null'],
                                    'description': (
                                        'Committed delivery date for this '
                                        'quantity split, ISO 8601 date '
                                        '(YYYY-MM-DD).'),
                                    },
                            },
                            'required': [
                                'product_code', 'party_product_code', 'ean',
                                'description', 'quantity',
                                'unit', 'unit_price', 'discount',
                                'tax_rate', 'tax_amount',
                                'line_total_excl_tax',
                                'line_total_incl_tax', 'delivery_date',
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
                'required': ['purchase_number', 'purchase_reference',
                    'issue_date', 'currency', 'seller', 'buyer',
                    'line_items', 'totals', 'notes'],
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
            purchase = None
            purchase_number = (data.get('purchase_number') or '').strip()
            purchase_reference = (
                data.get('purchase_reference') or '').strip()
            if purchase_reference:
                purchases = Purchase.search([
                        ('reference', '=', purchase_reference),
                        ('company', '=', self.document_company.id),
                        ('document', '=', None),
                        ])
                if len(purchases) == 1:
                    purchase, = purchases
            if not purchase and purchase_number:
                purchases = Purchase.search([
                        ('number', '=', purchase_number),
                        ('company', '=', self.document_company.id),
                        ('document', '=', None),
                        ])
                if len(purchases) == 1:
                    purchase, = purchases
            if not purchase and purchase_number:
                purchases = Purchase.search([
                        ('reference', '=', purchase_number),
                        ('company', '=', self.document_company.id),
                        ('document', '=', None),
                        ])
                if len(purchases) == 1:
                    purchase, = purchases
                    purchase_number, purchase_reference = (
                        purchase_reference, purchase_number)
            if not purchase and purchase_reference:
                purchases = Purchase.search([
                        ('number', '=', purchase_reference),
                        ('company', '=', self.document_company.id),
                        ('document', '=', None),
                        ])
                if len(purchases) == 1:
                    purchase, = purchases
                    purchase_number, purchase_reference = (
                        purchase_reference, purchase_number)
            if purchase:
                purchase.document = self
            else:
                purchase = Purchase()
                purchase.document = self
                purchase.company = self.document_company
                purchase.on_change_company()

        if (getattr(purchase, 'papyrus_lines', None)
                and not Transaction().context.get('papyrus_reinspect')):
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
            purchase.reference = purchase_reference or purchase_number
        if not purchase.purchase_date:
            purchase.purchase_date = tools.to_date(data['issue_date'])
        seller = data.get('seller', {})
        seller_name = (seller.get('name') or '').strip().upper()
        if seller_name:
            purchase.papyrus_name = seller_name

        lines = getattr(purchase, 'papyrus_lines', None)
        if not lines:
            lines = []
            for item in data.get('line_items', []):
                line = PapyrusPurchaseLine.build(item)
                lines.append(line)
            purchase.papyrus_lines = lines
        PapyrusPurchaseLine.find_product(purchase.party, lines)
        purchase.create_purchase_lines_from_papyrus_lines()
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

class Purchase(metaclass=PoolMeta):
    __name__ = 'purchase.purchase'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_name = fields.Char('Papyrus Name')
    papyrus_lines = fields.One2Many('papyrus.purchase.line', 'purchase',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

    def create_purchase_lines_from_papyrus_lines(self):
        PurchaseLine = Pool().get('purchase.line')
        PapyrusPurchaseLine = Pool().get('papyrus.purchase.line')

        purchase_lines = list(self.lines)
        for line in purchase_lines:
            if not line.desired_delivery_date:
                line.desired_delivery_date = (
                    line.delivery_date_store or line.delivery_date)

        papyrus_lines = sorted(
            [line for line in self.papyrus_lines
                if not line.purchase_line],
            key=lambda line: (
                line.product.id if line.product else 0,
                line.delivery_date or date.max,
                line.id or 0))
        if not purchase_lines:
            for papyrus_line in papyrus_lines:
                purchase_line = papyrus_line.get_purchase_line()
                if not purchase_line:
                    continue
                purchase_line.delivery_date_edit = True
                purchase_line.delivery_date_store = papyrus_line.delivery_date
                purchase_line.desired_delivery_date = (
                    papyrus_line.delivery_date)
                purchase_line.papyrus_line = papyrus_line
                # Keep the legacy link populated too. It is still used to
                # determine whether a Papyrus line has been materialized.
                papyrus_line.purchase_line = purchase_line
                purchase_lines.append(purchase_line)
        else:
            self._reconcile_purchase_lines(purchase_lines, papyrus_lines)

        if purchase_lines:
            PurchaseLine.save(purchase_lines)
        PapyrusPurchaseLine.save([
                line for line in papyrus_lines
                if line.purchase_line])

    def _reconcile_purchase_lines(self, purchase_lines, papyrus_lines):
        PurchaseLine = Pool().get('purchase.line')
        if (self.state not in {'draft', 'quotation'}
                or any(line.moves for line in purchase_lines)):
            raise UserError(gettext(
                'papyrus_model.msg_papyrus_purchase_lines_too_late',
                purchase=self.rec_name))
        remaining = {line: Decimal(str(line.quantity or 0))
            for line in purchase_lines}
        candidates = sorted(purchase_lines, key=lambda line: (
            line.product.id if line.product else 0,
            line.desired_delivery_date or date.max,
            line.id or 0))
        for papyrus_line in papyrus_lines:
            if not papyrus_line.product or not papyrus_line.quantity:
                continue
            if papyrus_line.quantity <= 0:
                continue
            quantity = papyrus_line.quantity
            for line in candidates:
                if quantity <= 0 or line.product != papyrus_line.product:
                    continue
                available = remaining[line]
                if available <= 0:
                    continue
                amount = min(quantity, available)
                if amount < available:
                    residual, = PurchaseLine.copy([line], default={
                        'quantity': available - amount,
                        'delivery_date_edit': True,
                        'delivery_date_store': line.delivery_date,
                        'papyrus_line': None,
                        })
                    residual.desired_delivery_date = (
                        line.desired_delivery_date)
                    candidates.insert(candidates.index(line) + 1, residual)
                    purchase_lines.append(residual)
                    remaining[residual] = available - amount
                line.quantity = amount
                line.delivery_date_edit = True
                line.delivery_date_store = papyrus_line.delivery_date
                line.papyrus_line = papyrus_line
                papyrus_line.purchase_line = line
                remaining[line] = Decimal(0)
                quantity -= amount
            if quantity:
                papyrus_line.purchase_line = None

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
            if not purchase.document:
                continue

            purchase.create_purchase_lines_from_papyrus_lines()
            purchase.save()

    @classmethod
    def quote(cls, purchases):
        Warning = Pool().get('res.user.warning')
        for purchase in purchases:
            pending = [line for line in purchase.papyrus_lines
                if not line.purchase_line]
            if pending:
                key = 'papyrus_pending_purchase_lines.%s' % purchase.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_pending_lines',
                            document=purchase.rec_name, total=len(pending)))
            missing = [line for line in purchase.lines
                if not line.papyrus_line
                and not getattr(line, 'freight_line', False)]
            if missing:
                key = 'papyrus_missing_purchase_lines.%s' % purchase.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_missing_purchase_lines',
                            document=purchase.rec_name,
                            total=len(missing)))
        super().quote(purchases)

    @classmethod
    def confirm(cls, purchases):
        Warning = Pool().get('res.user.warning')
        for purchase in purchases:
            pending = [line for line in purchase.papyrus_lines
                if not line.purchase_line]
            if pending:
                key = 'papyrus_pending_purchase_lines.%s' % purchase.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_pending_lines',
                            document=purchase.rec_name, total=len(pending)))
            missing = [line for line in purchase.lines
                if not line.papyrus_line
                and not getattr(line, 'freight_line', False)]
            if missing:
                key = 'papyrus_missing_purchase_lines.%s' % purchase.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_missing_purchase_lines',
                            document=purchase.rec_name,
                            total=len(missing)))
        super().confirm(purchases)

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


class PurchaseLine(metaclass=PoolMeta):
    __name__ = 'purchase.line'

    desired_delivery_date = fields.Date(
        'Desired Delivery Date', readonly=True)
    papyrus_line = fields.Many2One(
        'papyrus.purchase.line', 'Papyrus Line', ondelete='SET NULL')

    @classmethod
    def create(cls, vlist):
        lines = super().create(vlist)
        to_write = {}
        for line, values in zip(lines, vlist):
            desired = values.get('delivery_date_store')
            if line.desired_delivery_date or not desired:
                continue
            to_write.setdefault(desired, []).append(line)
        for desired, lines in to_write.items():
            cls.write(lines, {'desired_delivery_date': desired})
        return lines

    @classmethod
    def write(cls, *args):
        to_write = {}
        actions = iter(args)
        for lines, values in zip(actions, actions):
            desired = values.get('delivery_date_store')
            if not desired:
                continue
            lines = [line for line in lines
                if not line.desired_delivery_date]
            if lines:
                to_write.setdefault(desired, []).extend(lines)
        super().write(*args)
        for desired, lines in to_write.items():
            cls.write(lines, {'desired_delivery_date': desired})


class PapyrusPurchaseLine(ModelSQL, ModelView):
    __name__ = 'papyrus.purchase.line'

    purchase = fields.Many2One('purchase.purchase', 'Purchase', required=True,
        ondelete='CASCADE')
    product_code = fields.Char('Product Code')
    external_code = fields.Char('External Code')
    ean = fields.Char('EAN')
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
    purchase_lines = fields.One2Many(
        'purchase.line', 'papyrus_line', 'Purchase Lines')
    delivery_date = fields.Date('Delivery Date')
    purchase_line_matches = fields.Function(
        fields.Boolean('Purchase Line Matches'), 'get_purchase_line_matches')

    @classmethod
    def build(cls, data):
        line = cls()
        product_code = data.get('product_code')
        if isinstance(product_code, str):
            product_code = product_code.replace('\x00', '').strip() or None
        external_code = data.get('party_product_code')
        if isinstance(external_code, str):
            external_code = external_code.replace('\x00', '').strip() or None
        ean_code = data.get('ean')
        if isinstance(ean_code, str):
            ean_code = ean_code.replace('\x00', '').strip() or None
        description = data.get('description')
        if isinstance(description, str):
            description = description.replace('\x00', '').strip()
        line.product_code = product_code
        line.external_code = external_code
        line.ean = ean_code
        line.description = description
        line.quantity = tools.to_decimal(data.get('quantity'))
        line.unit_price = tools.to_decimal(data.get('unit_price'))
        line.discount_rate = tools.to_decimal(data.get('discount'))
        line.amount = tools.to_decimal(data.get('line_total_excl_tax'))
        line.delivery_date = (
            date.fromisoformat(data['delivery_date'])
            if data.get('delivery_date') else None)
        if line.discount_rate:
            line.discount_rate = abs(line.discount_rate)
        taxes = data.get('tax_rate')
        if taxes is not None:
            line.taxes = str(taxes)
        return line

    def get_purchase_line(self):
        PurchaseLine = Pool().get('purchase.line')

        purchase = self.purchase
        product = getattr(self, 'product', None)
        unit_price = getattr(self, 'unit_price', None)
        if not product or unit_price is None:
            return
        digits = PurchaseLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))
        purchase_line = PurchaseLine()
        purchase_line.purchase = purchase
        purchase_line.product = product
        purchase_line.on_change_product()
        purchase_line.description = getattr(self, 'description', None)
        purchase_line.quantity = getattr(self, 'quantity', None)
        purchase_line.delivery_date_edit = True
        purchase_line.delivery_date_store = self.delivery_date
        purchase_line.on_change_quantity()
        discount_rate = getattr(self, 'discount_rate', None)
        if discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        purchase_line.unit_price = unit_price.quantize(exp)
        purchase_line.on_change_taxes()
        return purchase_line

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
        purchase_lines = list(getattr(self, 'purchase_lines', []))
        if not purchase_lines:
            return False
        quantity = getattr(self, 'quantity', None)
        if (quantity is not None
                and sum((line.quantity or Decimal(0)
                    for line in purchase_lines), Decimal(0)) != quantity):
            return False
        unit_price = getattr(self, 'unit_price', None)
        if (unit_price is not None and any(
                not Document.amounts_match(line.unit_price, unit_price)
                for line in purchase_lines)):
            return False
        product = getattr(self, 'product', None)
        if (product is not None
                and any(line.product != product for line in purchase_lines)):
            return False
        return True

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name="amount"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name="purchase_lines"]',
                'visual', If(Bool(Eval('purchase_lines')),
                    If(Eval('purchase_line_matches', False),
                        'success', 'danger'), '')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        lines = [line for line in lines if not getattr(line, 'product', None)]
        if not lines:
            return
        pool = Pool()
        Product = pool.get('product.product')
        Identifier = pool.get('product.identifier')
        HistoryLine = pool.get('papyrus.purchase.line')
        try:
            ProductSupplier = pool.get('purchase.product_supplier')
        except KeyError:
            ProductSupplier = None

        values = []
        ean_codes = []
        for line in lines:
            description = getattr(line, 'description', None)
            product_code = getattr(line, 'product_code', None)
            external_code = getattr(line, 'external_code', None)
            ean_code = getattr(line, 'ean', None)
            if isinstance(description, str):
                description = description.replace('\x00', '').strip() or None
                line.description = description
            if isinstance(product_code, str):
                product_code = product_code.replace('\x00', '').strip() or None
                line.product_code = product_code
            if isinstance(external_code, str):
                external_code = external_code.replace('\x00', '').strip() or None
                line.external_code = external_code
            if isinstance(ean_code, str):
                ean_code = ean_code.replace('\x00', '').strip() or None
                line.ean = ean_code
            if product_code:
                values.append(product_code)
            if external_code:
                values.append(external_code)
            if description:
                values.append(description)
            if ean_code and ean.is_valid(ean_code):
                ean_codes.append(ean.compact(ean_code))
                values.append(ean.compact(ean_code))
        by_code = {}
        by_name = {}
        by_ean = {}
        history_by_code = {}
        history_by_description = {}
        if ean_codes:
            identifiers = Identifier.search([
                    ('type', '=', 'ean'),
                    ('code', 'in', list(set(ean_codes))),
                    ])
            for identifier in identifiers:
                code = ean.compact(identifier.code)
                if code in by_ean:
                    by_ean[code] = None
                else:
                    by_ean[code] = identifier.product
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
            ean_code = getattr(line, 'ean', None)
            product = (
                by_ean.get(ean.compact(ean_code))
                if ean_code and ean.is_valid(ean_code) else None)
            if product_code:
                product = product or by_code.get(product_code)
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
