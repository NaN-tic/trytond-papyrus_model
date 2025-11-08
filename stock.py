# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
import json
from trytond.pool import Pool, PoolMeta
from trytond.model import fields, ModelSQL, ModelView
from trytond.pyson import Eval, Bool, If
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

    def get_party(self, name):
        if self.model_type == 'shipment_in' and self.shipment_in:
            return self.shipment_in[0].supplier.id
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
        system = {
            "role": "system",
            "content": (
                "You are an expert at extracting structured data from incoming "
                "shipment documents. Return ONLY JSON (no markdown) valid per the "
                "provided schema. Use numbers for monetary/quantitative "
                "fields; use null when unknown. Extract seller/buyer info "
                "(names, VAT/tax ID, address, email, phone), document number, "
                "dates, currency, line items (codes, descriptions, quantities, "
                "unit prices, discounts, taxes, line totals), and totals."
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
                'required': ['shipment_number', 'issue_date',
                     'due_date', 'currency', 'seller', 'buyer', 'line_items',
                     'totals', 'notes'],
                'additionalProperties': False
            }
        }

    def guess_shipment_in(self):
        pool = Pool()
        Currency = pool.get('currency.currency')
        ShipmentIn = pool.get('stock.shipment.in')
        PapyrusShipmentInLine = pool.get('papyrus.shipment.in.line')

        if self.model_type != 'shipment_in':
            return

        if self.extracted_data:
            data = json.loads(self.extracted_data)
        else:
            llms = (self.queue.llms or '').split(' ')
            for llm in llms:
                try:
                    data = tools.llm(
                        messages=self.guess_shipment_in_messages(),
                        model=llm,
                        pdf_engine=self.queue.llm_pdf_engine,
                        schema=self.guess_shipment_in_schema())
                except Exception as e:
                    print(f'Error extracting shipment_in data with {llm}: {e}')
                    continue
                self.extracted_data = json.dumps(data, indent=4)
                self.save()
                break
            else:
                print('All LLMs failed to extract shipment_in data.')
                return

        if self.shipment_in:
            shipment = self.shipment_in[0]
        else:
            shipment = ShipmentIn()
            shipment.document = self
            shipment.company = self.document_company

        if not getattr(shipment, 'supplier', None):
            shipment.supplier = self.find_party(data.get('seller', {}))
            if not shipment.supplier:
                return
            shipment.on_change_supplier()

        if not getattr(shipment, 'warehouse', None):
            shipment.warehouse = self.guess_shipment_in_warehouse(shipment)
            if not shipment.warehouse:
                return
            shipment.on_change_warehouse()

        shipment.save()

        if not shipment.reference:
            shipment.reference = data['shipment_number']
        if not shipment.effective_date:
            shipment.effective_date = tools.to_date(data['issue_date'])

        lines = []
        for item in data.get('line_items', []):
            line = PapyrusShipmentInLine()
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
            line.move = None
            lines.append(line)

        PapyrusShipmentInLine.find_product(shipment.supplier, lines)
        shipment.papyrus_lines = lines
        currencies = Currency.search([('code', '=', data.get('currency'))],
            limit=1)
        if currencies:
            currency, = currencies
        else:
            currency = self.company.currency
        self.create_moves_from_papyrus_lines(shipment, currency)
        shipment.save()

    def create_moves_from_papyrus_lines(self, shipment, currency):
        pool = Pool()
        Move = pool.get('stock.move')

        for papyrus_line in shipment.papyrus_lines:
            if papyrus_line.move:
                continue
            if not papyrus_line.product:
                continue
            move = Move()
            move.shipment = shipment
            move.product = papyrus_line.product
            move.on_change_product()
            move.quantity = papyrus_line.quantity
            move.from_location = shipment.supplier.supplier_location
            move.to_location = shipment.warehouse.input_location
            move.company = shipment.company
            # TODO: Use correct UoM conversion
            move.unit_price = (papyrus_line.unit_price or Decimal(0)).quantize(
                Decimal('0.0001'))
            move.currency = currency
            papyrus_line.move = move

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


class ShipmentIn(metaclass=PoolMeta):
    __name__ = 'stock.shipment.in'
    document = fields.Many2One('papyrus.document', "Document")
    papyrus_lines = fields.One2Many('papyrus.shipment.in.line', 'shipment',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

    @classmethod
    def copy(cls, shipments, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('document', None)
        return super().copy(shipments, default=default)


class PapyrusShipmentInLine(ModelSQL, ModelView):
    __name__ = 'papyrus.shipment.in.line'

    shipment = fields.Many2One('stock.shipment.in', 'Shipment', required=True,
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
    move = fields.Many2One('stock.move', 'Move',
        ondelete='SET NULL')
    move_matches = fields.Function(fields.Boolean('Move Matches'),
            'get_move_matches')

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

    def get_move_matches(self, name):
        if not self.move:
            return False
        matches = True
        if self.quantity is not None:
            matches &= self.move.quantity == self.quantity
        if self.product is not None:
            matches &= self.move.product == self.product
        return matches

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree/field[@name=\"amount\"]',
                'visual', If(Eval('amount_matches', False), 'success', 'danger')),
            ('/tree/field[@name=\"move\"]',
                'visual', If(Eval('move_matches', False), 'success', 'danger')),
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
