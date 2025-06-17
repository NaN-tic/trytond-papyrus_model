# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from datetime import datetime
from trytond.model import fields, ModelView, Workflow
from trytond.config import config
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model.fields.selection import TranslatedSelection
from statistics import mode, StatisticsError

MODEL_TYPE = [
    (None, ''),
    ('invoice', 'Invoice'),
    ('sale', 'Sale'),
    ('shipment_in', 'Shipment In'),
    ]
MONTHS = (
    (1, ('gener', 'enero', 'january')),
    (2, ('febrer', 'febrero', 'february')),
    (3, ('març', 'marzo', 'march')),
    (4, ('abril', 'april')),
    (5, ('maig', 'mayo', 'may')),
    (6, ('juny', 'junio', 'june')),
    (7, ('juliol', 'julio', 'july')),
    (8, ('agost', 'agosto', 'august')),
    (9, ('setembre', 'septiembre', 'september')),
    (10, ('octubre', 'october')),
    (11, ('novembre', 'noviembre', 'november')),
    (12, ('desembre', 'diciembre', 'december')),
    )

available_model_types = config.get('papyrus', 'model_types', default='').split(',')

class Queue(metaclass=PoolMeta):
    'Papyrus Queue'
    __name__ = 'papyrus.queue'
    model_type = fields.Selection(MODEL_TYPE, 'Model Type', states={
            'invisible': Eval('type') != 'document',
            })

    def get_document(self, filename):
        document = super().get_document(filename)
        document.model_type = self.model_type
        return document


class Document(metaclass=PoolMeta):
    'Papyrus Document'
    __name__ = 'papyrus.document'
    model_type = fields.Selection(MODEL_TYPE, 'Model Type')
    party = fields.Function(fields.Many2One('party.party', 'Party',
            context={
                'company': Eval('company', -1),
            },
            depends=['company']),
        'get_party', searcher='search_party')
    invoice = fields.One2Many('account.invoice', 'document', "Account Invoice",
        size=1, add_remove=[('document', '=', None)], context={
            'type': 'in',
            }, states={
            'invisible': (Eval('model_type') != 'invoice'),
            })
    sale = fields.One2Many('sale.sale', 'document', "Sale", size=1,
        add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'sale',
            })
    shipment_in = fields.One2Many('stock.shipment.in', 'document',
        "Shipment In", size=1, add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'shipment_in',
            })
    guessed_company = fields.Many2One('company.company', 'Guessed Company')
    guessed_model_type = fields.Selection(MODEL_TYPE, 'Guessed Model Type')

    @classmethod
    def __setup__(cls):
        super(Document, cls).__setup__()
        # Fields to check the company
        cls._check_company = {'invoice', 'sale', 'shipment_in'}

    def get_model_type_name(self, records):
        Model = Pool().get('ir.model')

        if self.model_type:
            t = TranslatedSelection('model_type')
            model_type = t.__get__(self, self)
        else:
            record = records[0]
            model, = Model.search([('name', '=', record.__name__)], limit=1)
            model_type = model.string
        return model_type

    def get_party(self, name):
        if self.model_type == 'invoice' and self.invoice:
            return self.invoice[0].party.id
        elif self.model_type == 'sale' and self.sale:
            return self.sale[0].party.id
        elif self.model_type == 'shipment_in' and self.shipment_in:
            return self.shipment_in[0].supplier.id

    @classmethod
    def search_party(cls, name, clause):
        return ['OR',
            ('invoice.party',) + tuple(clause[1:]),
            ('sale.party',) + tuple(clause[1:]),
            ('shipment_in.supplier',) + tuple(clause[1:]),
            ]

    @classmethod
    def delete(cls, documents):
        exists = cls.model_exists(documents)
        if exists:
            records, document = exists
            model_type_name = document.get_model_type_name(records)

            raise UserError(gettext('papyrus_model.'
                    'msg_cannot_delete_with_related_record',
                    document=document.rec_name,
                    record=records[0].rec_name,
                    model_type=model_type_name))
        super().delete(documents)

    @classmethod
    @ModelView.button
    @Workflow.transition('pending')
    def pending(cls, documents):
        exists = cls.model_exists(documents)
        if exists:
            records, document = exists
            model_type_name = document.get_model_type_name(records)

            raise UserError(gettext('papyrus_model.'
                    'msg_cannot_pending_with_related_record',
                    document=document.rec_name,
                    record=records[0].rec_name,
                    model_type=model_type_name))
        super().pending(documents)

    @classmethod
    def model_exists(cls, documents):
        with Transaction().set_user(0):
            for document in cls.browse([x.id for x in documents]):
                for field in ('invoice', 'sale', 'shipment_in'):
                    records = getattr(document, field)
                    if records:
                        return records, document

    @classmethod
    def validate(cls, documents):
        super(Document, cls).validate(documents)
        for document in documents:
            document.validate_company()

    def validate_company(self):
        pool = Pool()
        Document = pool.get('papyrus.document')

        with Transaction().set_user(0):
            document = Document(self.id)
            for field in document._check_company:
                field_to_check = getattr(self, field)
                if (document.company and field_to_check and
                        document.company != field_to_check[0].company):
                    raise UserError(gettext(
                        'papyrus_model.msg_cannot_change_company_%s' % field,
                        document=document.number,
                        model=field_to_check[0].rec_name))


    def scan_engines(self):
        super().scan_engines()
        yield 'text'
        if self.text and self.text.strip():
            yield 'textboxes'
        else:
            yield 'tesseract'

    def scan(self):
        super().scan()
        self.guess_company()
        self.guess_model_type()
        if self.model_type:
            getattr(self, 'guess_%s' % self.model_type)()

    def guess_company(self):
        pool = Pool()
        Company = pool.get('company.company')

        if self.company:
            return

        def normalize_code(code):
            # Try to remove non-alphanumeric symbols
            for char in '-. ,':
                code = code.replace(char, '')
            code = code.lower()
            return code

        identifiers = {}
        for company in Company.search([]):
            for identifier in company.party.identifiers:
                if not identifier.code:
                    continue
                code = normalize_code(identifier.code)
                identifiers[code] = company
                if identifier.type == 'eu_vat':
                    code = code[2:]
                    identifiers[code] = company

        for box in self.boxes:
            text = box.text
            if text is None:
                continue
            text = text.strip()
            if not text:
                continue

            text = normalize_code(text)
            if text in identifiers:
                self.guessed_company = identifiers[text]
                self.company = self.guessed_company
                break

    def guess_model_type(self):
        if self.model_type:
            return
        if not self.text:
            return

        def find_words(type_, words):
            text = self.text.lower()
            for word in words:
                if word in text:
                    self.guessed_model_type = type_
                    self.model_type = self.guessed_model_type
                    return True
            return False

        if 'invoice' in available_model_types:
            if find_words('invoice', ['factura', 'invoice', 'abono']):
                return

        if 'shipment_in' in available_model_types:
            if find_words('shipment_in', ['albarán', 'albarà', 'albaran', 'albara',
                        'shipment', 'delivery']):
                return

        if 'sale' in available_model_types:
            if find_words('sale', ['pedido', 'comanda', 'order']):
                return

    def guess_party(self, type_=None):
        pool = Pool()
        Party = pool.get('party.party')
        Company = pool.get('company.company')
        Identifier = pool.get('party.identifier')

        def normalize_code(code):
            # Try to remove non-alphanumeric symbols
            for char in '-. ,':
                code = code.replace(char, '')
            code = code.lower()
            return code

        has_party_company = hasattr(Party, 'companies')
        company_id= self.company.id

        # Check type_ only if party_customer or party_supplier modules are
        # activated
        domain = [('party.active', '=', True)]
        if type_ == 'customer' and hasattr(Party, 'customer'):
            domain += [('party.customer', '=', True)]
        elif type_ == 'supplier' and hasattr(Party, 'supplier'):
            domain += [('party.supplier', '=', True)]

        # party_company
        if has_party_company:
            domain += [['OR',
                ('companies', 'in', []),
                ('companies', 'in', [company_id]),
                ]]

        companies = [x.party.id for x in Company.search([])]
        parties = {}
        for identifier in Identifier.search(domain + [
                    ('party', 'not in', companies),
                    ('type', 'in', Party.tax_identifier_types()),
                    ]):
            code = normalize_code(identifier.code)
            parties[code] = identifier.party
            if identifier.type == 'eu_vat':
                code = code[2:]
                parties[code] = identifier.party

        for box in self.boxes:
            text = box.text
            if text is None:
                continue
            text = text.strip()
            if not text:
                continue
            text = normalize_code(text)
            if text in parties:
                return parties[text]

    def guess_date(self):
        Date = Pool().get('ir.date')
        year = Date().today().year
        min_year = year - 1
        max_year = year + 1

        def parse_date(text):
            for month, names in MONTHS:
                for name in names:
                    text = text.replace(name, str(month))

            for month, names in MONTHS:
                for name in names:
                    # Frequently months are abbreviated to the first 3 letters
                    # sometimes with a dot at the end
                    text = text.replace(name[:3] + '.', str(month))
                    text = text.replace(name[:3], str(month))

            # Remove empty spaces
            text = text.replace(' ', '')

            for pattern in ('%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y', '%d-%m-%y',
                    '%d.%m.%Y', '%d.%m.%y'):
                try:
                    date = datetime.strptime(text, pattern)
                    if date.year >= min_year and date.year <= max_year:
                        return date.date()
                except ValueError:
                    pass

        for box in self.boxes:
            date = box.text and parse_date(box.text.strip())
            if date:
                return date

    def guess_invoice(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')

        if not self.company or self.invoice:
            return
        with Transaction().set_context(company=self.company.id):
            party = self.guess_party('supplier')
            if not party:
                return
            invoice = None
            pending_lines = InvoiceLine.search([
                    ('invoice', '=', None),
                    ('party', '=', party),
                    ('invoice_type', '=', 'in'),
                    ('company', '=', self.company.id),
                    ], limit=1)
            if not pending_lines:
                domain = [
                    ('party', '=', party),
                    ('type', '=', 'in'),
                    ('untaxed_amount', '>', Decimal(0)),
                    ('state', 'in', ['posted', 'paid']),
                    ('company', '=', self.company.id),
                    ]
                last_invoices = Invoice.search(domain,
                    order=[('invoice_date', 'DESC')], limit=5)
                # Invoices that have at least one line with an origin are not
                # elligible.
                # Note that we cannot use a domain that looks like
                # "('lines.origin', '=', None)" to pick the last_invoices
                # because that would return invoices that have at least one
                # line without origin, but the invoice may have other lines
                # with origin and we do not want to duplicate those.
                invalid_invoices = set(Invoice.search(domain + [
                        ('lines.origin', '!=', None),
                        ], order=[('invoice_date', 'DESC')], limit=5))
                for last_invoice in last_invoices:
                    if last_invoice not in invalid_invoices:
                        invoice, = Invoice.copy([last_invoice], default={
                                'reference': None,
                                'invoice_date': None,
                                })
                        break

            if not invoice:
                invoice = self._get_invoice()
                invoice.party = party
                invoice.on_change_party()
            invoice.invoice_date = self.guess_date()
            invoice._update_account()
            invoice.document = self
            invoice.on_change_lines()
            invoice.save()
            self.guess_employee([('invoice.party', '=', party)])

    def guess_sale(self):
        if not self.company or self.sale:
            return
        with Transaction().set_context(company=self.company.id):
            party = self.guess_party('customer')
            if not party:
                return
            sale = self._get_sale()
            sale.party = party
            sale.on_change_party()
            sale.sale_date = self.guess_date()
            sale.document = self
            sale.save()
            self.guess_employee([('sale.party', '=', party)])

    def guess_shipment_in_warehouse(self, shipment):
        Move = Pool().get('stock.move')

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

    def guess_shipment_in(self):
        if not self.company or self.shipment_in:
            return
        with Transaction().set_context(company=self.company.id):
            party = self.guess_party('supplier')
            if not party:
                return
            shipment = self._get_shipment_in()
            shipment.supplier = party
            shipment.on_change_supplier()
            if not shipment.warehouse:
                shipment.warehouse = self.guess_shipment_in_warehouse(shipment)
                if not shipment.warehouse:
                    return
            shipment.effective_date = self.guess_date()
            shipment.document = self
            shipment.save()
            self.guess_employee([('shipment_in.supplier', '=', party)])

    def get_record(self):
        record = super().get_record()
        if not record:
            if self.model_type == 'invoice' and self.invoice:
                record = self.invoice[0]
            elif self.model_type == 'sale' and self.sale:
                record = self.sale[0]
            elif self.model_type == 'shipment_in' and self.shipment_in:
                record = self.shipment_in[0]
            else:
                raise UserError(gettext('papyrus_model.'
                        'msg_cannot_process_without_related_record'))
        return record

    @fields.depends('model_type', 'invoice', 'sale', 'shipment_in')
    def on_change_model_type(self):
        if self.model_type:
            if not getattr(self, self.model_type):
                obj = getattr(self, '_get_%s' % self.model_type)()
                setattr(self, self.model_type, [obj])

        for type_, _ in self.__class__.model_type.selection:
            if type_ and self.model_type != type_:
                setattr(self, type_, [])

    def _get_invoice(self):
        Invoice = Pool().get('account.invoice')
        defaults = Invoice.default_get(list(Invoice._fields.keys()),
            with_rec_name=False)
        invoice = Invoice(**defaults)
        invoice.type = 'in'
        invoice.set_journal()
        return invoice

    def _get_sale(self):
        Sale = Pool().get('sale.sale')
        defaults = Sale.default_get(list(Sale._fields.keys()),
            with_rec_name=False)
        sale = Sale(**defaults)
        return sale

    def _get_shipment_in(self):
        ShipmentIn = Pool().get('stock.shipment.in')
        defaults = ShipmentIn.default_get(list(ShipmentIn._fields.keys()),
            with_rec_name=False)
        shipment_in = ShipmentIn(**defaults)
        return shipment_in

    def guess_employee(self, domain):
        if self.employee:
            return
        rows = self.search([
                (self.model_type, '!=', None),
                ('state', '=', 'processed'),
                ('company', '=', self.company)
                ] + domain, limit=5, order=[('id', 'DESC')])
        employees = [r.employee.id for r in rows if r.employee]
        if employees:
            try:
                self.employee = mode(employees)
            except StatisticsError:
                self.employee = employees[0]
