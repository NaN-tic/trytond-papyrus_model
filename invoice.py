# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import json
from trytond.pool import PoolMeta, Pool
from trytond.model import fields, ModelSQL, ModelView
from trytond.wizard import Wizard, StateAction
from trytond.pyson import PYSONEncoder, Eval, Bool
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

        if not getattr(invoice, 'number', None):
            invoice.reference = data['invoice_number']
        if not getattr(invoice, 'invoice_date', None):
            invoice.invoice_date = tools.to_date(data['issue_date'])

        lines = []
        for item in data.get('line_items', []):
            line = PapyrusInvoiceLine()
            line.product_code = item.get('product_code')
            line.description = item.get('description')
            line.quantity = item.get('quantity')
            line.unit_price = item.get('unit_price')
            line.discount_rate = item.get('discount')
            taxes = item.get('tax_rate')
            if taxes is not None:
                line.taxes = str(taxes)
            line.subtotal = item.get('line_total_excl_tax')
            lines.append(line)

        PapyrusInvoiceLine.find_product(lines)
        invoice.papyrus_lines = lines
        invoice.save()

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
    papyrus_lines = fields.One2Many('papyrus.invoice.line', 'invoice',
        'Papyrus Lines', states={
            'invisible': ~Bool(Eval('papyrus_lines')),
            })

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

    # TODO: Ideally we should remove the line when both the invoice and the document
    # are deleted
    invoice = fields.Many2One('account.invoice', 'Invoice', required=True,
        ondelete='SET NULL')
    product_code = fields.Char('Product Code')
    description = fields.Text('Description')
    quantity = fields.Numeric('Quantity')
    unit_price = fields.Numeric('Unit Price')
    discount_rate = fields.Numeric('Discount (%)')
    taxes = fields.Char('Taxes')
    subtotal = fields.Numeric('Subtotal')
    product = fields.Many2One('product.product', 'Product')
    invoice_line = fields.Many2One('account.invoice.line', 'Invoice Line',
        ondelete='SET NULL')

    @classmethod
    def find_product(cls, lines):
        pool = Pool()
        Product = pool.get('product.product')

        to_search = []
        for line in lines:
            if line.product_code:
                to_search.append(line.product_code)
            if line.description:
                to_search.append(line.description)
        products = set(Product.search([('code', 'in', to_search)]))
        products |= set(Product.search([('name', 'in', to_search)]))
        products = Product.browse(products)
        by_code = {x.code: x for x in products}
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
