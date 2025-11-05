# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from trytond.model import fields, ModelView, Workflow
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model.fields.selection import TranslatedSelection
from statistics import mode, StatisticsError
from . import tools


class Queue(metaclass=PoolMeta):
    __name__ = 'papyrus.queue'
    model_type = fields.Selection('_get_model_type', 'Model Type', states={
            'invisible': Eval('type') != 'document',
            })
    llm_classifier = fields.Char('Classifier LLM')
    llms = fields.Char('LLMs')
    llm_pdf_engine = fields.Selection([
            (None, ''),
            ('mistral-ocr', 'Mistral OCR (best for scanned documents)'),
            ('native', 'Native (best for born-digital PDFs)'),
            ('pdf-text', 'PDF Text (balanced)'),
            ], 'LLM PDF Engine')

    @classmethod
    def _get_model_type(cls):
        return [(None, '')]

    def get_document(self, filename):
        document = super().get_document(filename)
        document.model_type = self.model_type
        return document


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'
    model_type = fields.Selection('_get_model_type', 'Model Type')
    party = fields.Function(fields.Many2One('party.party', 'Party',
            context={
                'company': Eval('document_company', -1),
            },
            depends=['document_company']),
        'get_party', searcher='search_party')
    guessed_company = fields.Many2One('company.company', 'Guessed Company')
    guessed_model_type = fields.Selection('_get_model_type', 'Guessed Model Type')
    extracted_data = fields.Text('Extracted Data', readonly=True)

    @classmethod
    def _get_model_type(cls):
        Queue = Pool().get('papyrus.queue')
        return Queue._get_model_type()

    @classmethod
    def __setup__(cls):
        super().__setup__()
        # Fields to check the company
        cls._check_company = set()

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
            guesser = getattr(self, 'guess_%s' % self.model_type)
            guesser()

    def guess_model_types(self):
        return {}

    def guess_model_type_schema(self):
        return {
            'name': 'document_classification',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'model_type': {
                        'type': 'string',
                        'enum': list(self.guess_model_types().keys()),
                    }
                },
                'required': ['model_type']
            }
        }

    def guess_model_type(self):
        if self.model_type:
            return
        llms = (self.queue.llm_classifier or '').split(' ')
        for llm in llms:
            try:
                response = tools.llm(messages=self.guess_model_type_messages(),
                    model=llm,
                    pdf_engine=self.queue.llm_pdf_engine,
                    schema=self.guess_model_type_schema(),
                    max_tokens=256,
                    )
            except tools.LLMError as e:
                print('Error classifying document with LLM %s: %s' % (llm, e))
                continue
            self.model_type = response.get('model_type')
            break

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

    def guess_model_type_messages(self):
        system = {
            "role": "system",
            "content": (
                "You are an expert at classifying business documents "
                "(invoices, orders, delivery notes, receipts). Return ONLY "
                "JSON (no markdown) valid per the provided schema."
            )
        }
        types = '\n'.join(f'- {key}: {value}' for key, value
            in self.guess_model_types().items())
        user = {
            "role": "user",
            "content": [{
                    "type": "text",
                    "text": (
                        "Classify this document text and output STRICT JSON "
                        "matching the schema. No extra text. Parse this "
                        "business document and output STRICT JSON matching the "
                        "schema. No extra text. Here're the document types:"
                        f"\n\n{types}\n\n"
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

    def get_party(self, name):
        return

    @classmethod
    def _search_party(cls, clause):
        return []

    @classmethod
    def search_party(cls, name, clause):
        clauses = cls._search_party(clause)
        if not clauses:
            return
        return ['OR', *clauses]

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

        for document in documents:
            document.model_type = None
            document.guessed_company = None
            document.guessed_model_type = None
            document.extracted_data = None
        cls.save(documents)
        super().pending(documents)

    @classmethod
    def model_exists(cls, documents):
        with Transaction().set_user(0, set_context=True):
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

        with Transaction().set_user(0, set_context=True):
            document = Document(self.id)
            for field in document._check_company:
                field_to_check = getattr(self, field)
                if (document.company and field_to_check and
                        document.company != field_to_check[0].company):
                    raise UserError(gettext(
                        'papyrus_model.msg_cannot_change_company_%s' % field,
                        document=document.number,
                        model=field_to_check[0].rec_name))


    def guess_company(self):
        if self.company:
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

    def guess_invoiceXXXXXXXXXXXXXXXXXXXXXXXXX(self):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')

        if not self.company or self.invoice:
            return

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

        for type_, _ in self._get_model_type():
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
