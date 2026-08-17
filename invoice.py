# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import json
from datetime import date, timedelta
from decimal import Decimal
from stdnum import ean
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder, Eval, Bool, If
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.transaction import Transaction
from . import tools


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('invoice', 'Supplier Invoice'),
            ]


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    papyrus_group_lines_by_tax = fields.Boolean('Papyrus Group Lines by Tax')


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
        cls._check_model_exists.add('invoice')

    def get_party(self, name):
        if self.model_type == 'invoice' and self.invoice:
            Party = Pool().get('party.party')
            party = self.invoice[0].party
            if Party.search([('id', '=', party.id)], limit=1):
                return party.id
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
        info = self.get_company_info()
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from invoice "
                "documents where the seller is the supplier and the buyer is "
                f"{info}. Return ONLY JSON (no markdown) valid per the "
                "provided schema. Use numbers for monetary/quantitative "
                "fields; use null when unknown. Extract seller/buyer info "
                "(names, VAT/tax ID), document number, dates, "
                "currency, our order number, supplier order number, supplier "
                "delivery note number, line items (codes, EANs, descriptions, "
                "quantities, unit prices, taxes), and totals. If a line contains both "
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
                    'our_order_number': {
                        'type': ['string', 'null'],
                        },
                    'party_order_number': {
                        'type': ['string', 'null'],
                        },
                    'party_shipment_number': {
                        'type': ['string', 'null'],
                        },
                    'seller': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'},
                            'vat': {'type': ['string', 'null']},
                        },
                        'required': ['name', 'vat'],
                        'additionalProperties': False
                    },
                    'buyer': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'},
                            'vat': {'type': ['string', 'null']},
                        },
                        'required': ['name', 'vat'],
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
                                'discount': {
                                    'type': 'number',
                                    'description': ('Discount rate as a percentage, e.g., 10 for 10%. '
                                    'If the document shows a discount amount, calculate the discount rate '
                                    'as (discount_amount / (quantity * unit_price)) * 100.'),
                                    },
                                'line_total_excl_tax': {
                                    'type': 'number'},
                                'tax_rate': {'type': 'number'},
                            },
                            'required': [
                                'product_code', 'party_product_code', 'ean',
                                 'description', 'quantity',
                                 'unit', 'unit_price', 'discount',
                                 'line_total_excl_tax', 'tax_rate',
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
                        'type': ['string', 'null'],
                        },
                },
                'required': ['invoice_number', 'issue_date',
                     'due_date', 'currency', 'our_order_number',
                     'party_order_number', 'party_shipment_number', 'seller',
                     'buyer', 'line_items', 'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def should_import_data(self, data):
        return bool(data)

    def guess_invoice(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        Currency = pool.get('currency.currency')
        PapyrusInvoiceLine = pool.get('papyrus.invoice.line')

        if self.model_type != 'invoice':
            return

        messages = self.guess_invoice_messages()
        schema = self.guess_invoice_schema()
        data = self.extract_data_with_llm('invoice', messages, schema)
        if not self.should_import_data(data):
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

        if (getattr(invoice, 'papyrus_lines', None)
                and not Transaction().context.get('papyrus_reinspect')):
            invoice.papyrus_lines = []
            invoice.save()

        if not getattr(invoice, 'party', None):
            seller = data.get('seller', {})
            invoice.party = self.find_invoice_party_from_data(seller, data)
            if not invoice.party:
                tools.logger.warning(
                    'Document %s extracted invoice data but no '
                    'supplier party was matched; skipping invoice creation '
                    '(seller_name=%s, seller_vat=%s)',
                    self.id, seller.get('name'), seller.get('vat'))
                return
            invoice.on_change_party()

        currency_code = (data.get('currency') or '').upper()
        if currency_code:
            currencies = Currency.search([('code', '=', currency_code)],
                limit=1)
            if currencies:
                invoice.currency, = currencies

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
        seller = data.get('seller', {})
        seller_name = (seller.get('name') or '').strip().upper()
        if seller_name:
            invoice.papyrus_name = seller_name

        lines = getattr(invoice, 'papyrus_lines', None)

        if lines:
            PapyrusInvoiceLine.find_product(invoice.party, lines)
        else:
            lines = []
            for item in data.get('line_items', []):
                line = PapyrusInvoiceLine.build(item)
                lines.append(line)
            PapyrusInvoiceLine.find_product(invoice.party, lines)
            if invoice.party.papyrus_group_lines_by_tax:
                grouped = {}
                for line in lines:
                    key = getattr(line, 'taxes', None) or ''
                    if key not in grouped:
                        grouped[key] = [line]
                        continue
                    grouped[key].append(line)
                lines = []
                for tax, tax_lines in grouped.items():
                    if len(tax_lines) == 1:
                        lines.append(tax_lines[0])
                        continue
                    amount = Decimal(0)
                    products = set()
                    for line in tax_lines:
                        line_amount = getattr(line, 'amount', None)
                        if line_amount is None:
                            quantity = getattr(line, 'quantity', None)
                            unit_price = getattr(line, 'unit_price', None)
                            if quantity is not None and unit_price is not None:
                                discount_rate = getattr(
                                    line, 'discount_rate', None)
                                if discount_rate:
                                    unit_price *= (
                                        Decimal('100') - discount_rate
                                        ) / Decimal('100')
                                line_amount = quantity * unit_price
                        if line_amount is not None:
                            amount += line_amount
                        product = getattr(line, 'product', None)
                        if product:
                            products.add(product)
                    line = PapyrusInvoiceLine()
                    line.description = 'Taxes %s' % (tax or '0')
                    line.quantity = Decimal(1)
                    line.unit_price = amount
                    line.amount = amount
                    line.taxes = tax or None
                    if len(products) == 1:
                        line.product, = products
                    lines.append(line)
            invoice.papyrus_lines = lines

        PapyrusInvoiceLine.find_invoice_line(
            invoice.party, lines, data)
        invoice.create_invoice_lines_from_papyrus_lines()
        invoice.save()

    def find_invoice_party_from_data(self, data, extracted_data=None):
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
            name, model_name='account.invoice', role_field='supplier',
            related_party_field='party', related_date_field='invoice_date',
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

class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'
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
    papyrus_lines = fields.One2Many('papyrus.invoice.line', 'invoice',
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

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_modify_exclude.add('document')
        cls._buttons.update({
                'create_lines': {
                    'invisible': ~Bool(Eval('papyrus_lines')),
                    'depends': ['papyrus_lines'],
                    },
                })

    def create_invoice_lines_from_papyrus_lines(self):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        PapyrusInvoiceLine = pool.get('papyrus.invoice.line')

        to_save = []
        to_update = []
        for papyrus_line in getattr(self, 'papyrus_lines', []):
            invoice_line = getattr(papyrus_line, 'invoice_line', None)
            if invoice_line:
                if not invoice_line.invoice:
                    invoice_line.invoice = self
                    to_update.append(invoice_line)
                continue
            invoice_line = papyrus_line.get_invoice_line()
            if not invoice_line:
                continue
            papyrus_line.invoice_line = invoice_line
            to_save.append(papyrus_line)

        if to_save:
            PapyrusInvoiceLine.save(to_save)
        if to_update:
            InvoiceLine.save(to_update)
        if to_save or to_update:
            self.on_change_lines()

    @classmethod
    @ModelView.button
    def create_lines(cls, invoices):
        for invoice in invoices:
            if not invoice.document:
                continue

            invoice.create_invoice_lines_from_papyrus_lines()
            invoice.save()

    @classmethod
    def post(cls, invoices):
        Warning = Pool().get('res.user.warning')
        for invoice in invoices:
            pending = [line for line in invoice.papyrus_lines
                if not line.invoice_line]
            if pending:
                key = 'papyrus_pending_invoice_lines.%s' % invoice.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_pending_lines',
                            document=invoice.rec_name, total=len(pending)))
        super().post(invoices)

    @classmethod
    def copy(cls, invoices, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(invoices, default=default)

    @classmethod
    def create(cls, vlist):
        invoices = super().create(vlist)
        for invoice in invoices:
            if invoice.type != 'in' or not invoice.document:
                continue
            if not invoice.document.extracted_data:
                continue
            try:
                data = json.loads(invoice.document.extracted_data)
            except (TypeError, ValueError):
                continue
            seller = data.get('seller') or {}
            name = (seller.get('name') or '').strip().upper()
            if not name:
                continue
            if invoice.papyrus_name == name:
                continue
            invoice.papyrus_name = name
            invoice.save()
        return invoices

    @classmethod
    def write(cls, *args):
        super().write(*args)
        actions = iter(args)
        for invoices, values in zip(actions, actions):
            if 'party' not in values:
                continue
            for invoice in invoices:
                if invoice.type != 'in' or not invoice.document:
                    continue
                if not invoice.document.extracted_data:
                    continue
                try:
                    data = json.loads(invoice.document.extracted_data)
                except (TypeError, ValueError):
                    continue
                seller = data.get('seller') or {}
                name = (seller.get('name') or '').strip().upper()
                if not name:
                    continue
                if invoice.papyrus_name == name:
                    continue
                super().write([invoice], {'papyrus_name': name})

class PapyrusInvoiceLine(ModelSQL, ModelView):
    __name__ = 'papyrus.invoice.line'

    invoice = fields.Many2One('account.invoice', 'Invoice', required=True,
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
    invoice_line = fields.Many2One('account.invoice.line', 'Invoice Line',
        ondelete='SET NULL')
    invoice_line_issue = fields.Function(fields.Char('Invoice Line Issue'),
            'get_invoice_line_issue')

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
        if line.discount_rate:
            line.discount_rate = abs(line.discount_rate)
        taxes = data.get('tax_rate')
        if taxes is not None:
            line.taxes = str(taxes)
        return line

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

    def get_invoice_line(self):
        InvoiceLine = Pool().get('account.invoice.line')

        invoice = self.invoice
        product = getattr(self, 'product', None)
        unit_price = getattr(self, 'unit_price', None)
        if not product or unit_price is None:
            return
        digits = InvoiceLine.unit_price.digits[1]
        exp = Decimal(str(10.0 ** -digits))
        invoice_line = InvoiceLine()
        invoice_line.invoice = invoice
        invoice_line.product = product
        invoice_line.on_change_product()
        invoice_line.description = getattr(self, 'description', None)
        invoice_line.quantity = getattr(self, 'quantity', None)
        discount_rate = getattr(self, 'discount_rate', None)
        if discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        invoice_line.unit_price = unit_price.quantize(exp)
        return invoice_line

    def get_invoice_line_issue(self, name):
        Document = Pool().get('papyrus.document')
        invoice_line = getattr(self, 'invoice_line', None)
        if not invoice_line:
            if getattr(self, 'product', None):
                return gettext('papyrus_model.msg_invoice_line_not_found',
                    line=self.rec_name, invoice=self.invoice.rec_name)
            return gettext('papyrus_model.msg_invoice_line_missing_product',
                line=self.rec_name, invoice=self.invoice.rec_name)
        issues = []
        product = getattr(self, 'product', None)
        if product is not None and invoice_line.product != product:
            issues.append(gettext('papyrus_model.msg_mismatch_product',
                    papyrus=product.rec_name,
                    invoice=(invoice_line.product.rec_name
                        if invoice_line.product else '')))
        quantity = getattr(self, 'quantity', None)
        if quantity is not None and invoice_line.quantity != quantity:
            issues.append(gettext('papyrus_model.msg_mismatch_quantity',
                    papyrus=quantity,
                    invoice=invoice_line.quantity))
        unit_price = getattr(self, 'unit_price', None)
        discount_rate = getattr(self, 'discount_rate', None)
        if unit_price is not None and discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        if (unit_price is not None
                and not Document.amounts_match(invoice_line.unit_price,
                    unit_price)):
            issues.append(gettext('papyrus_model.msg_mismatch_unit_price',
                    papyrus=unit_price,
                    invoice=invoice_line.unit_price))
        return ', '.join(issues)

    def get_line_candidates(self, candidates):
        Document = Pool().get('papyrus.document')

        def normalize(value):
            if not value:
                return ''
            return ''.join(char for char in value.upper() if char.isalnum())

        def external_codes_for_invoice_line(invoice_line):
            codes = set()
            origin = getattr(invoice_line, 'origin', None)
            product_supplier = getattr(
                origin, 'product_supplier', None) if origin else None
            if product_supplier and product_supplier.code:
                codes.add(product_supplier.code)
            for move in getattr(invoice_line, 'stock_moves', []):
                origin = getattr(move, 'origin', None)
                product_supplier = getattr(origin, 'product_supplier', None)
                if product_supplier and product_supplier.code:
                    codes.add(product_supplier.code)
            return {normalize(code) for code in codes if code}

        product = getattr(self, 'product', None)
        external_code = normalize(getattr(self, 'external_code', None))
        line_candidates = []
        for invoice_line in candidates:
            if product and invoice_line.product == product:
                line_candidates.append(invoice_line)
                continue
            if (external_code
                    and external_code in external_codes_for_invoice_line(
                        invoice_line)):
                line_candidates.append(invoice_line)
        unit_price = getattr(self, 'unit_price', None)
        discount_rate = getattr(self, 'discount_rate', None)
        if unit_price is not None and discount_rate:
            unit_price *= (Decimal('100') - discount_rate) / Decimal('100')
        if unit_price is not None:
            matching = [invoice_line for invoice_line in line_candidates
                if Document.amounts_match(invoice_line.unit_price, unit_price)]
            if matching:
                line_candidates = matching
        return line_candidates

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name="amount"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name="invoice_line"]',
                'visual', If(Bool(Eval('invoice_line')),
                    If(Bool(Eval('invoice_line_issue')),
                        'danger', 'success'), '')),
            ]

    @classmethod
    def find_product(cls, party, lines):
        lines = [line for line in lines if not getattr(line, 'product', None)]
        if not lines:
            return
        pool = Pool()
        Product = pool.get('product.product')
        Identifier = pool.get('product.identifier')
        HistoryLine = pool.get('papyrus.invoice.line')
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
            history_domain = [('invoice.party', '=', party),
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

    @classmethod
    def find_invoice_line(cls, party, lines, data):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        try:
            Purchase = pool.get('purchase.purchase')
        except KeyError:
            Purchase = None

        candidate_invoice_lines = InvoiceLine.search([
                ('invoice', '=', None),
                ])
        candidates = []
        for invoice_line in candidate_invoice_lines:
            if getattr(invoice_line, 'type', None) != 'line':
                continue
            origin = getattr(invoice_line, 'origin', None)
            purchase = getattr(origin, 'purchase', None) if origin else None
            if getattr(purchase, 'party', None) == party:
                candidates.append(invoice_line)
                continue
            for move in getattr(invoice_line, 'stock_moves', []):
                shipment = getattr(move, 'shipment', None)
                if getattr(shipment, 'supplier', None) == party:
                    candidates.append(invoice_line)
                    break

        def normalize(value):
            if not value:
                return ''
            return ''.join(char for char in value.upper() if char.isalnum())

        def purchase_for_invoice_line(invoice_line):
            origin = getattr(invoice_line, 'origin', None)
            purchase = getattr(origin, 'purchase', None) if origin else None
            if purchase:
                return purchase
            for move in getattr(invoice_line, 'stock_moves', []):
                origin = getattr(move, 'origin', None)
                purchase = getattr(origin, 'purchase', None) if origin else None
                if purchase:
                    return purchase

        def shipment_for_invoice_line(invoice_line):
            for move in getattr(invoice_line, 'stock_moves', []):
                shipment = getattr(move, 'shipment', None)
                if shipment:
                    return shipment

        our_order_number = normalize(data.get('our_order_number'))
        party_order_number = normalize(data.get('party_order_number'))
        party_shipment_number = normalize(data.get('party_shipment_number'))
        purchase_matched = False
        our_order_number_value = (data.get('our_order_number') or '').strip()
        party_order_number_value = (
            data.get('party_order_number') or '').strip()
        purchase_domain = []
        if our_order_number_value:
            purchase_domain.extend([
                    ('number', '=', our_order_number_value),
                    ('reference', '=', our_order_number_value),
                    ])
        if party_order_number_value:
            purchase_domain.extend([
                    ('number', '=', party_order_number_value),
                    ('reference', '=', party_order_number_value),
                    ])
        if purchase_domain and Purchase:
            purchases = Purchase.search([
                    ('party', '=', party),
                    ['OR'] + purchase_domain,
                    ])
            if purchases:
                matching = []
                for invoice_line in candidates:
                    purchase = purchase_for_invoice_line(invoice_line)
                    if purchase and purchase in purchases:
                        matching.append(invoice_line)
                candidates = matching
                purchase_matched = True
        if not purchase_matched and our_order_number:
            matching = []
            for invoice_line in candidates:
                purchase = purchase_for_invoice_line(invoice_line)
                if purchase and normalize(purchase.number) == our_order_number:
                    matching.append(invoice_line)
            if matching:
                candidates = matching
        elif party_order_number:
            matching = []
            for invoice_line in candidates:
                purchase = purchase_for_invoice_line(invoice_line)
                if purchase and normalize(purchase.reference) == party_order_number:
                    matching.append(invoice_line)
            if matching:
                candidates = matching
        elif party_shipment_number:
            matching = []
            for invoice_line in candidates:
                shipment = shipment_for_invoice_line(invoice_line)
                if shipment and normalize(shipment.reference) == party_shipment_number:
                    matching.append(invoice_line)
            if matching:
                candidates = matching

        used = set()
        for line in lines:
            invoice_line = getattr(line, 'invoice_line', None)
            if invoice_line:
                used.add(invoice_line.id)

        for line in lines:
            if getattr(line, 'invoice_line', None):
                continue
            line_candidates = line.get_line_candidates([
                    invoice_line for invoice_line in candidates
                    if invoice_line.id not in used])
            if not line_candidates:
                continue
            issue_date = tools.to_date(data.get('issue_date')) or date.today()
            line_candidates.sort(key=lambda invoice_line: (
                    abs(((getattr(purchase_for_invoice_line(invoice_line),
                                    'purchase_date', None)
                                or getattr(shipment_for_invoice_line(invoice_line),
                                    'effective_date', None)
                                or issue_date) - issue_date).days),
                    invoice_line.id))
            line.invoice_line = line_candidates[0]
            used.add(line_candidates[0].id)


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
