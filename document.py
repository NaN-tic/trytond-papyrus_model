# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import io
from PIL import Image, ImageDraw
from decimal import Decimal
from datetime import datetime
from statistics import mode, StatisticsError
from trytond.model import fields, ModelSQL, ModelView, Workflow
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model.fields.selection import TranslatedSelection
from .utils import Rectangle, Sentencer


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


class DocumentBox(metaclass=PoolMeta):
    __name__ = 'papyrus.document.box'
    category = fields.Char('category')
    categories = fields.Char('Categories')


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


class Value(ModelSQL, ModelView):
    'Papyrus Document Value'
    __name__ = 'papyrus.document.value'
    document = fields.Many2One('papyrus.document', 'Document', required=True,
        ondelete='CASCADE')
    field = fields.Char('Field', required=True)
    line = fields.Integer('Line')
    text = fields.Char('Text')
    value_reference = fields.Reference('Value', selection='get_value_reference')
    page = fields.Integer('Page')
    x0 = fields.Float('x0')
    y0 = fields.Float('x0')
    x1 = fields.Float('x1')
    y1 = fields.Float('y1')

    @classmethod
    def _get_value_reference(cls):
        return ['party.party', 'party.identifier', 'product.product',
            'currency.currency']

    @classmethod
    def get_value_reference(cls):
        Model = Pool().get('ir.model')
        models = cls._get_value_reference()
        models = Model.search([
                ('model', 'in', models),
                ])
        return [('', '')] + [(m.model, m.name) for m in models]


class Document(metaclass=PoolMeta):
    'Papyrus Document'
    __name__ = 'papyrus.document'
    model_type = fields.Selection(MODEL_TYPE, 'Model Type')
    party = fields.Function(fields.Many2One('party.party', 'Party'),
        'get_party', searcher='search_party')
    invoice = fields.One2Many('account.invoice', 'document', "Account Invoice",
        size=1, add_remove=[('document', '=', None)], context={
            'type': 'in',
            }, states={
            'invisible': Eval('model_type') != 'invoice',
            }, depends=['model_type'])
    sale = fields.One2Many('sale.sale', 'document', "Sale", size=1,
        add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'sale',
            }, depends=['model_type'])
    shipment_in = fields.One2Many('stock.shipment.in', 'document',
        "Shipment In", size=1, add_remove=[('document', '=', None)],
        states={
            'invisible': Eval('model_type') != 'shipment_in',
            }, depends=['model_type'])
    guessed_company = fields.Many2One('company.company', 'Guessed Company')
    guessed_model_type = fields.Selection(MODEL_TYPE, 'Guessed Model Type')
    values = fields.One2Many('papyrus.document.value', 'document', 'Values',
        readonly=True)

    def get_model_type_name(self, records):
        Model = Pool().get('ir.model')

        if self.model_type:
            t = TranslatedSelection('model_type')
            model_type = t.__get__(self, self)
        else:
            record = records[0]
            model, = Model.search([('model', '=', record.__name__)], limit=1)
            model_type = model.name
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

    def guess_boxes(self):
        boxes = [Rectangle(x) for x in self.boxes if x.type == 'text'
            and getattr(x, 'page', None) in (1, None)]
        boxes = sorted(boxes, key=lambda b: (b.y0, b.x0))

        bests = []

        while boxes:
            print()
            print('*' * 50)
            box = boxes[0]
            print('Picked box: ', box)
            sentencer = Sentencer(box, boxes)
            print('Processing Max Sentence:', sentencer.max_sentence)

            best = None
            best_weight = 0.0
            for combination in sentencer.combinations():
                weight = 0.0
                count = 0
                for box in combination:
                    box.basic_ner()
                    print('Box: %s, Category: %s, Weight: %.2f' % (box,
                            box.main_category, box.main_weight))
                    if box.main_weight > 0:
                        weight += box.main_weight
                        # Only count boxes with main_weight > 1 for the average
                        # TODO: To improve
                        count += 1

                if count > 0:
                    weight /= count
                if (not best
                        or weight > best_weight
                        or (weight == best_weight
                            and len(combination) < len(best))):
                    best = combination
                    best_weight = weight
            print('Best:', best)
            bests += best

            for box in sentencer.max_sentence:
                boxes.remove(box)

        print('#' * 50)
        print('#' * 50)
        print('#' * 50)
        print(bests)
        print('#' * 50)
        print('#' * 50)
        def find_before(box, boxes):
            r = Rectangle(box)
            height = r.height
            r.y0 += height * 0.15
            r.y1 -= height * 0.15
            r.x1 = r.x0
            r.x0 = 0

            nearest = None
            for b in boxes:
                if not (set(b.text) - {'.', ' ', '…'}):
                    # If the text of b, onlyl contains dots or spaces, simply
                    # ignore it. In some rare cases, there is is a string of
                    # dots such as:
                    #
                    # Total  ..........     410,19
                    #
                    # We want to ignore the dots in those cases.
                    continue
                if b == box or not b.intersects(r):
                    continue
                if not nearest or b.x1 > nearest.x1:
                    nearest = b
            return nearest

        def find_above(box, boxes):
            r = Rectangle(box)
            r.y1 = r.y0
            r.y0 = 0

            nearest = None
            for b in boxes:
                if b == box or not b.intersects(r):
                    continue
                if not nearest or b.y1 > nearest.y1:
                    nearest = b
            return nearest

        def find_header(box, boxes):
            r = Rectangle(box)
            r.y1 = r.y0
            r.y0 = 0

            nearest = None
            for b in boxes:
                if (not b.main_category
                        or not b.main_category.endswith('-header')):
                    continue
                if b == box or not b.intersects(r):
                    continue
                if not nearest or b.y1 > nearest.y1:
                    nearest = b
            return nearest

        for box in bests:
            if box.main_category and box.main_category.endswith('-label'):
                continue
            #if box.main_category not in (None, 'integer', 'float', 'date'):
            #    continue
            #if box.main_weight > 0.95:
                #continue
            before = find_before(box, bests)
            if before and before.text == ':':
                before = find_before(before, bests)
            #print('Box: %s Before: %s' % (box, before))
            if before and before.main_category:
                if before.main_category.endswith('-label'):
                    category = before.main_category.split('-label')[0]
                    add = True
                    if category == 'invoice_number':
                        if not box.has_a_number():
                            add = False
                    elif category == 'invoice_date':
                        if box.type != 'date':
                            add = False
                    elif 'amount' in category:
                        if not box.is_number():
                            add = False
                    if add:
                        # Clean categories otherwise 'integer' will weight more
                        box.categories = []
                        box.categories.append((category, 0.9))
                        box.compute_main_category()
                        continue

            above = find_above(box, bests)
            #print('Box: %s Above: %s' % (box, before))
            if above and above.main_category:
                if above.main_category.endswith('-label'):
                    category = above.main_category.split('-label')[0]
                    add = True
                    if category == 'invoice_number':
                        if not box.has_a_number():
                            add = False
                    elif category == 'invoice_date':
                        if box.type != 'date':
                            add = False
                    elif 'amount' in category:
                        if not box.is_number():
                            add = False
                    if add:
                        # Clean categories otherwise 'integer' will weight more
                        box.categories = []
                        box.categories.append((category, 0.9))
                        box.compute_main_category()
                        continue

            header = find_header(box, bests)
            #print('Box: %s Header: %s' % (box, before))
            if header:
                category = header.main_category.split('-header')[0]
                # Clean categories otherwise 'integer' will weight more
                box.categories = []
                box.categories.append((category, 0.9))
                box.compute_main_category()

        print('#' * 50)
        print('#' * 50)
        print('#' * 50)
        print(bests)
        print('#' * 50)
        print('#' * 50)

        Value = Pool().get('papyrus.document.value')
        Value.delete(Value.search([('document', '=', self.id)]))

        values = []
        processed = set()
        for box in bests:
            if box.main_category in ('invoice_number', 'invoice_date',
                    'total_amount', 'tax_identifier'):
                if box.main_category in ('invoice_number', 'invoice_date'):
                    if box.main_category in processed:
                        continue
                    processed.add(box.main_category)
                print('%s: %s' % (box.main_category, box.text))
                value = Value()
                value.field = box.main_category
                value.text = box.text
                value.page = 1
                value.x0 = box.x0
                value.y0 = box.y0
                value.x1 = box.x1
                value.y1 = box.y1
                values.append(value)

        if 'invoice_date' not in processed:
            date_value = None
            first = (999, 999)
            for box in bests:
                if box.type == 'date':
                    pos = (box.y0, box.x0)
                    if pos > first:
                        continue
                    first = pos
                    date_value = Value()
                    date_value.field = 'invoice_date'
                    date_value.text = box.text
                    date_value.page = 1
                    date_value.x0 = box.x0
                    date_value.y0 = box.y0
                    date_value.x1 = box.x1
                    date_value.y1 = box.y1
            if date_value:
                values.append(date_value)


        self.values = values
        self.save()

        print('-' * 50)

    @fields.depends('values')
    def on_change_with_image(self, name=None):
        image = super().on_change_with_image(name)
        if image:
            im = Image.open(io.BytesIO(image))
            if im.getbands() != ('R', 'G', 'B'):
                # If image is not 'RGB' convert it so we can add color
                # rectangles
                im = im.convert('RGB')
            draw = ImageDraw.Draw(im)
            xscale = 1.385
            yscale = 1.385
            OUTLINE = (192, 0, 0)
            for value in (self.values or []):
                if (value.page or 1) != self.current_page:
                    continue
                x0 = value.x0 or 0
                y0 = value.y0 or 0
                x1 = value.x1 or 0
                y1 = value.y1 or 0
                draw.rectangle(
                    (x0 * xscale, y0 * yscale, x1 * xscale, y1 * yscale),
                    outline=OUTLINE)
            image = io.BytesIO()
            im.save(image, format='png')
            image = image.getvalue()
        return image

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
        self.guess_boxes()
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

        if find_words('invoice', ['factura', 'invoice', 'abono']):
            return

        if find_words('shipment_in', ['albarán', 'albarà', 'albaran', 'albara',
                    'shipment', 'delivery']):
            return

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

        # Check type_ only if party_customer or party_supplier modules are
        # activated
        if type_ == 'customer' and hasattr(Party, 'customer'):
            domain = [('party.customer', '=', True)]
        elif type_ == 'supplier' and hasattr(Party, 'supplier'):
            domain = [('party.supplier', '=', True)]
        else:
            domain = []

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
            date = parse_date(box.text.strip())
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
            invoice.payment_term = invoice.on_change_with_payment_term()
            invoice.account = invoice.on_change_with_account()
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
        if self.model_type == 'invoice' and self.invoice:
            record, = self.invoice
        elif self.model_type == 'sale' and self.sale:
            record, = self.sale
        elif self.model_type == 'shipment_in' and self.shipment_in:
            record, = self.shipment_in
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
        invoice.on_change_type()
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
