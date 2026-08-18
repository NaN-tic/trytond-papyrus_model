# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import json
from datetime import date, timedelta
from decimal import Decimal
from stdnum import ean
from trytond.pool import Pool, PoolMeta
from trytond.model import fields, ModelSQL, ModelView
from trytond.pyson import Eval, Bool, If
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.transaction import Transaction
from . import tools


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'

    @classmethod
    def _get_model_type(cls):
        return super()._get_model_type() + [
            ('shipment_in', 'Shipment In'),
            ]


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    shipment_in = fields.One2Many('stock.shipment.in', 'document',
        "Shipment In", size=1, add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'shipment_in',
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_company.add('shipment_in')
        cls._check_model_exists.add('shipment_in')

    def get_party(self, name):
        if self.model_type == 'shipment_in' and self.shipment_in:
            Party = Pool().get('party.party')
            party = self.shipment_in[0].supplier
            if Party.search([('id', '=', party.id)], limit=1):
                return party.id
        return super().get_party(name)

    @classmethod
    def _search_party(cls, clause):
        return super()._search_party(clause) + [
            ('shipment_in.supplier',) + tuple(clause[1:]),
            ]

    def guess_model_types(self):
        types = super().guess_model_types()
        types.update({
                'shipment_in': 'Incoming Supplier Shipment',
                })
        return types

    def guess_shipment_in_warehouse(self, shipment):
        pool = Pool()
        Move = pool.get('stock.move')
        Location = pool.get('stock.location')

        warehouses = Location.search([
                ('type', '=', 'warehouse'),
                ])
        if len(warehouses) == 1:
            return warehouses[0]

        # Only if there are moves and all go to the same location
        # we can guess the warehouse
        moves = Move.search([
                ('company', '=', self.company),
                ('state', '=', 'draft'),
                ('from_location', '=', shipment.supplier.supplier_location),
                ('to_location.type', '=', 'storage'),
                ])
        if not moves:
            return
        location = moves[0].to_location
        for move in moves:
            if move.to_location != location:
                return
        return location.warehouse

    def guess_shipment_in_messages(self):
        info = self.get_company_info()
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from incoming "
                "shipment documents where the seller is the supplier and the "
                f"buyer is {info}. Return ONLY JSON (no markdown) valid per "
                "the provided schema. Use numbers for monetary/quantitative "
                "fields; use null when unknown. Extract seller/buyer info "
                "(names, VAT/tax ID, address, email, phone), document number, "
                "our purchase number, supplier purchase reference, dates, "
                "currency, line items (codes, EANs, descriptions, quantities, "
                "unit prices, discounts, taxes, line totals), and totals. If "
                "both purchase numbers are present, purchase_number is our "
                "purchase/order number and purchase_reference is the "
                "supplier's purchase/order reference. "
                "If unsure, return the closest values in those fields. If "
                "a line contains both our/internal product code and the "
                "supplier's product code, keep them separate: product_code is "
                "our/internal code and party_product_code is the supplier code. "
                "Return in unit_price the price of exactly one billed unit. If "
                "the document has a separate price-base column, often labeled "
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

    def guess_shipment_in_schema(self):
        return {
            'name': 'shipment_in',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'shipment_number': {
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
                    'purchase_number': {
                        'type': ['string', 'null'],
                        },
                    'purchase_reference': {
                        'type': ['string', 'null'],
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
                                'line_total_incl_tax': {'type': 'number'}
                            },
                            'required': [
                                'product_code', 'party_product_code', 'ean',
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
                'required': ['shipment_number', 'issue_date',
                     'due_date', 'currency', 'purchase_number',
                     'purchase_reference', 'seller', 'buyer', 'line_items',
                     'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def guess_shipment_in(self):
        pool = Pool()
        ShipmentIn = pool.get('stock.shipment.in')
        PapyrusShipmentInLine = pool.get('papyrus.shipment.in.line')

        if self.model_type != 'shipment_in':
            return

        messages = self.guess_shipment_in_messages()
        schema = self.guess_shipment_in_schema()
        data = self.extract_data_with_llm('shipment_in', messages, schema)
        if not data:
            return

        if self.shipment_in:
            shipment = self.shipment_in[0]
        else:
            shipment = ShipmentIn()
            shipment.document = self
            shipment.company = self.document_company

        if (getattr(shipment, 'papyrus_lines', None)
                and not Transaction().context.get('papyrus_reinspect')):
            shipment.papyrus_lines = []
            shipment.save()

        if not getattr(shipment, 'supplier', None):
            seller = data.get('seller', {})
            shipment.supplier = self.find_shipment_in_party_from_data(
                seller, data)
            if not shipment.supplier:
                tools.logger.warning(
                    'Document %s extracted shipment data but no '
                    'supplier party was matched; skipping shipment creation '
                    '(seller_name=%s, seller_vat=%s)',
                    self.id, seller.get('name'), seller.get('vat'))
                return
            shipment.on_change_supplier()

        if not getattr(shipment, 'warehouse', None):
            shipment.warehouse = self.guess_shipment_in_warehouse(shipment)
            if not shipment.warehouse:
                tools.logger.warning(
                    'Document %s extracted shipment data but no warehouse was '
                    'matched; skipping shipment creation', self.id)
                return
            shipment.on_change_warehouse()

        shipment.save()

        if not shipment.reference:
            shipment.reference = data['shipment_number']
        if not shipment.effective_date:
            shipment.effective_date = tools.to_date(data['issue_date'])
        seller_name = (seller.get('name') or '').strip().upper()
        if seller_name:
            shipment.papyrus_name = seller_name

        lines = getattr(shipment, 'papyrus_lines', None)
        if not lines:
            lines = []
            for item in data.get('line_items', []):
                line = PapyrusShipmentInLine.build(item)
                lines.append(line)
            shipment.papyrus_lines = lines
        PapyrusShipmentInLine.find_product(shipment.supplier, lines)
        PapyrusShipmentInLine.find_move(shipment, lines, data)
        shipment.save()

    def find_shipment_in_party_from_data(self, data, extracted_data=None):
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
            name, model_name='stock.shipment.in', role_field='supplier',
            related_party_field='supplier', related_date_field='effective_date',
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

class ShipmentIn(metaclass=PoolMeta):
    __name__ = 'stock.shipment.in'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_name = fields.Char('Papyrus Name')
    papyrus_lines = fields.One2Many('papyrus.shipment.in.line', 'shipment',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'sync_papyrus_line_moves': {
                    'invisible': ~Bool(Eval('papyrus_lines')),
                    'depends': ['papyrus_lines'],
                    },
                })

    @classmethod
    @ModelView.button
    def sync_papyrus_line_moves(cls, shipments):
        Move = Pool().get('stock.move')
        to_save = []

        for shipment in shipments:
            for papyrus_line in getattr(shipment, 'papyrus_lines', []):
                move = getattr(papyrus_line, 'move', None)
                if not move:
                    continue
                if move.shipment != shipment:
                    move.shipment = shipment
                    to_save.append(move)

        if to_save:
            Move.save(to_save)

    @classmethod
    def receive(cls, shipments):
        Warning = Pool().get('res.user.warning')
        for shipment in shipments:
            pending = [line for line in shipment.papyrus_lines
                if not line.move]
            if pending:
                key = 'papyrus_pending_shipment_lines.%s' % shipment.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_pending_lines',
                            document=shipment.rec_name, total=len(pending)))
        super().receive(shipments)

    @classmethod
    def do(cls, shipments):
        Warning = Pool().get('res.user.warning')
        for shipment in shipments:
            pending = [line for line in shipment.papyrus_lines
                if not line.move]
            if pending:
                key = 'papyrus_pending_shipment_lines.%s' % shipment.id
                if Warning.check(key):
                    raise UserWarning(key, gettext(
                            'papyrus_model.msg_papyrus_pending_lines',
                            document=shipment.rec_name, total=len(pending)))
        super().do(shipments)

    @classmethod
    def copy(cls, shipments, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(shipments, default=default)

    @classmethod
    def create(cls, vlist):
        shipments = super().create(vlist)
        for shipment in shipments:
            if not shipment.document:
                continue
            if not shipment.document.extracted_data:
                continue
            try:
                data = json.loads(shipment.document.extracted_data)
            except (TypeError, ValueError):
                continue
            seller = data.get('seller') or {}
            name = (seller.get('name') or '').strip().upper()
            if not name:
                continue
            if shipment.papyrus_name == name:
                continue
            shipment.papyrus_name = name
            shipment.save()
        return shipments

    @classmethod
    def write(cls, *args):
        super().write(*args)
        actions = iter(args)
        for shipments, values in zip(actions, actions):
            if 'supplier' not in values:
                continue
            for shipment in shipments:
                if not shipment.supplier or not shipment.document:
                    continue
                if not shipment.document.extracted_data:
                    continue
                try:
                    data = json.loads(shipment.document.extracted_data)
                except (TypeError, ValueError):
                    continue
                seller = data.get('seller') or {}
                name = (seller.get('name') or '').strip().upper()
                if not name:
                    continue
                if shipment.papyrus_name == name:
                    continue
                super().write([shipment], {'papyrus_name': name})


class PapyrusShipmentInLine(ModelSQL, ModelView):
    __name__ = 'papyrus.shipment.in.line'

    shipment = fields.Many2One('stock.shipment.in', 'Shipment', required=True,
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
    move = fields.Many2One('stock.move', 'Move',
        ondelete='SET NULL')
    move_matches = fields.Function(fields.Boolean('Move Matches'),
            'get_move_matches')

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

    def get_move_matches(self, name):
        Document = Pool().get('papyrus.document')
        move = getattr(self, 'move', None)
        if not move:
            return False
        quantity = getattr(self, 'quantity', None)
        if quantity is not None and move.quantity != quantity:
            return False
        unit_price = getattr(self, 'unit_price', None)
        if (unit_price is not None
                and move.unit_price is not None
                and not Document.amounts_match(move.unit_price, unit_price)):
            return False
        product = getattr(self, 'product', None)
        if product is not None and move.product != product:
            return False
        return True

    def get_line_candidates(self, candidates):
        Document = Pool().get('papyrus.document')
        product = getattr(self, 'product', None)
        if not product:
            return []
        candidates = [move for move in candidates if move.product == product]
        unit_price = getattr(self, 'unit_price', None)
        if unit_price is not None:
            candidates = [move for move in candidates
                if (move.unit_price is not None
                    and Document.amounts_match(move.unit_price, unit_price))]
        return candidates

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name=\"amount\"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name=\"move\"]',
                'visual', If(Bool(Eval('move')),
                    If(Eval('move_matches', False),
                        'success', 'danger'), '')),
            ]

    @classmethod
    def find_move(cls, shipment, lines, data):
        pool = Pool()
        Move = pool.get('stock.move')
        try:
            Purchase = pool.get('purchase.purchase')
        except KeyError:
            Purchase = None

        candidates = Move.search([
                ('shipment', '=', None),
                ('state', '=', 'draft'),
                ('from_location', '=', shipment.supplier.supplier_location),
                ('to_location', '=', shipment.warehouse.input_location),
                ])
        purchase_number = (data.get('purchase_number') or '').strip()
        purchase_reference = (data.get('purchase_reference') or '').strip()
        purchase_domain = []
        if purchase_number:
            purchase_domain.extend([
                    ('number', '=', purchase_number),
                    ('reference', '=', purchase_number),
                    ])
        if purchase_reference:
            purchase_domain.extend([
                    ('number', '=', purchase_reference),
                    ('reference', '=', purchase_reference),
                    ])
        if purchase_domain and Purchase:
            purchases = Purchase.search([
                    ('party', '=', shipment.supplier),
                    ['OR'] + purchase_domain,
                    ])
            if purchases:
                PurchaseLine = pool.get('purchase.line')
                candidates = [move for move in candidates
                    if (isinstance(move.origin, PurchaseLine)
                        and move.origin.purchase in purchases)]
        used = {line.move.id for line in lines if getattr(line, 'move', None)}

        for line in lines:
            if getattr(line, 'move', None):
                continue
            line_candidates = line.get_line_candidates([
                    move for move in candidates if move.id not in used])
            if not line_candidates:
                continue
            line_candidates.sort(key=lambda move: move.id)
            line.move = line_candidates[0]
            used.add(line_candidates[0].id)

    @classmethod
    def find_product(cls, party, lines):
        lines = [line for line in lines if not getattr(line, 'product', None)]
        if not lines:
            return
        pool = Pool()
        Product = pool.get('product.product')
        Identifier = pool.get('product.identifier')
        HistoryLine = pool.get('papyrus.shipment.in.line')
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
            history_domain = [('shipment.supplier', '=', party),
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
