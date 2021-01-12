# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import re
import ngram
import stdnum
import json
from decimal import Decimal
from datetime import datetime
from statistics import mode, StatisticsError
from trytond.model import fields, ModelView, Workflow
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model.fields.selection import TranslatedSelection
from trytond.cache import Cache

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
NUMBER_SET = set('0123456789')

class Rectangle:
    def __init__(self, *args):
        if len(args) == 1:
            r = args[0]
            for p in ('x0', 'y0', 'x1', 'y1', 'text'):
                assert hasattr(r, p)
                setattr(self, p, getattr(r, p))
        else:
            assert len(args) == 5
            self.x0 = args[0]
            self.y0 = args[1]
            self.x1 = args[2]
            self.y1 = args[3]
            self.text = args[4]
        self.check()

    def check(self):
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError('coordinates are invalid')

    def intersects(self, other):
        self.check()
        if min(self.x1, other.x1) < max(self.x0, other.x0):
            return False
        if min(self.y1, other.y1) < max(self.y0, other.y0):
            return False
        return True


class DocumentBox(metaclass=PoolMeta):
    __name__ = 'papyrus.document.box'
    category = fields.Char('category')
    categories = fields.Char('Categories')
    _caches = Cache('papyrus.document.box')

    def basic_ner_zip(self):
        pool = Pool()
        Zip = pool.get('country.zip')
        g = self._caches.get('zips')
        if not g:
            zips = [x.zip.lower() for x in Zip.search([])]
            g = ngram.NGram(zips)
            self._caches.set('zips', g)
        for item in g.search(self.text.lower(), threshold=0.9):
            return 'zip', item[1]

    def basic_ner_city(self):
        pool = Pool()
        Zip = pool.get('country.zip')
        g = self._caches.get('cities')
        if not g:
            cities = [x.city.lower() for x in Zip.search([])]
            g = ngram.NGram(cities)
            self._caches.set('cities', g)
        for item in g.search(self.text.lower(), threshold=0.9):
            return 'city', item[1]

    def basic_ner_subdivision(self):
        pool = Pool()
        Subdivision = pool.get('country.subdivision')
        g = self._caches.get('subdivisions')
        if not g:
            subdivisions = [x.name.lower() for x in Subdivision.search([])]
            g = ngram.NGram(subdivisions)
            self._caches.set('subdivisions', g)
        for item in g.search(self.text.lower(), threshold=0.9):
            return 'subdivision', item[1]

    def basic_ner_country(self):
        pool = Pool()
        Country = pool.get('country.country')
        g = self._caches.get('countries')
        if not g:
            countries = [x.name.lower() for x in Country.search([])]
            g = ngram.NGram(countries)
            self._caches.set('countries', g)
        for item in g.search(self.text.lower(), threshold=0.9):
            return 'country', item[1]

    def basic_ner_street(self):
        text = self.text.lower()
        text = text.strip()

        if len(text) < 10:
            return
        if (text.startswith('c/') or text.startswith('carrer')
                or text.startswith('calle')):
            return 'street', 0.6
        if (text.endswith('street') or text.endswith('st.')
                or text.endswith('st')):
            return 'street', 0.6
        if text.endswith('avenue') or text.endswith('ave.'):
            return 'street', 0.6

        # If starts with letters and has a 1 to 3 digit number at the end
        # it is likely a street
        text = text.replace(',', ' ')
        ending = text.split()[-1]
        try:
            int(ending)
        except:
            return
        beginning = set(' '.join(text.split()[:-1]))
        if not beginning & NUMBER_SET:
            return 'street', 0.6


    def basic_ner_date(self):
        Date = Pool().get('ir.date')
        year = Date().today().year
        min_year = year - 1
        max_year = year + 1

        def parse_date(text):
            for pattern in ('%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y', '%d-%m-%y',
                    '%d.%m.%Y', '%d.%m.%y'):
                try:
                    date = datetime.strptime(text, pattern)
                    if date.year >= min_year and date.year <= max_year:
                        return date
                except ValueError:
                    pass

        date = parse_date(self.text)
        if date:
            return 'date', 0.98

    def basic_ner_phone(self):
        text = self.text.replace('.', '').replace(' ', '').replace('-', '')
        text = text.replace('(', '').replace(')', '')
        if len(text) <= 5:
            return
        # If any character is different from '+' or a number it is not a phone
        # number
        invalid = any(x for x in text if x not in '+0123456789')
        if invalid:
            return
        return 'phone', 0.98

    def basic_ner_email(self):
        emails = re.findall("([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
            self.text)
        if len(emails) == 1:
            return 'e-mail', 0.98

    def basic_ner_url(self):
        text = self.text.lower()
        text = text.strip()
        if text.startswith('http'):
            return 'url', 0.98
        if text.startswith('www'):
            return 'url', 0.98

    def basic_ner_integer(self):
        text = self.text.strip()
        remains = set(text) - NUMBER_SET
        if not remains:
            return 'integer', 1
        text = text.replace(' ', '')
        if not remains:
            return 'integer', 0.98

    @staticmethod
    def to_float(text):
        idx_dot = text.find('.')
        idx_comma = text.find(',')
        if idx_dot >= 0 and idx_comma >= 0:
            if idx_dot > idx_comma:
                text = text.replace(',', '')
            else:
                text = text.replace('.', '')
                text = text.replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return

    def basic_ner_float(self):
        text = self.text.strip()
        value = self.to_float(text)
        if not value is None:
            return 'float', 0.95
        text = text.replace(' ', '')
        value = self.to_float(text)
        if not value is None:
            return 'float', 0.92

    def basic_ner_page(self):
        text = self.text.replace(' ', '')
        if not '/' in text:
            return
        ps = text.split('/')
        if len(ps) != 2:
            return
        try:
            [int(x) for x in ps]
        except ValueError:
            return
        return 'page', 0.95

    def basic_ner_tax_identifier(self):
        pool = Pool()
        Party = pool.get('party.party')

        text = self.text.strip()
        if len(text) < 6:
            return
        for type in Party.tax_identifier_types():
            # TODO: It's not obvious why we should only check
            # tax_identifier_types.
            # TODO: Given that we have a patch that discarts non eu-vat tax
            # identifiers, we prepend 'ES'
            module = stdnum.get_cc_module(*type.split('_', 1))
            try:
                if module and module.is_valid(text):
                    break
            except:
                pass
        else:
            return
        return 'tax_identifier', 1

    def basic_ner_currency(self):
        pool = Pool()
        Currency = pool.get('currency.currency')

        text = self.text.strip().lower()
        currencies = Currency.search([])
        for currency in currencies:
            if text == currency.symbol.lower():
                return 'currency', 0.99
            if text == currency.name.lower() or text == currency.code.lower():
                return 'currency', 0.95

    def basic_ner_bic(self):
        if stdnum.bic.is_valid(self.text.strip()):
            # There are lots of false positives with words such as 'CANTIDAD'
            # or 'FERNANDO', so we cannot assign a high probability
            return 'bic', 0.5

    def basic_ner_iban(self):
        text = self.text.strip()
        if stdnum.iban.is_valid(text):
            return 'iban', 1
        text = text.replace(' ', '')
        if stdnum.iban.is_valid(text):
            return 'iban', 0.95

    def basic_ner_payment_type(self):
        text = self.text.strip()
        if text in ('cheque', 'transferencia', 'recibo'):
            return 'payment-type', 0.99

    def basic_ner_payment_term(self):
        text = self.text.strip()
        if text in ('10 dias', '20 dias', '30 dias', '60 dias'):
            return 'payment-term', 0.99

    def basic_ner_label(self, category, labels, threshold=0.95):
        text = self.text.lower()
        text = text.replace(':', '')
        text = text.strip()
        g = self._caches.get(category)
        if not g:
            g = ngram.NGram(labels)
            self._caches.set(category, g)
        for item in g.search(text, threshold=threshold):
            return category, item[1]

    def basic_ner(self):
        categories = []
        for ner in ('zip', 'integer', 'float', 'city', 'subdivision',
                'country', 'street', 'date', 'phone', 'email', 'url', 'page',
                'currency', 'bic', 'iban', 'payment_type', 'payment_term',
                'tax_identifier'):
            method = getattr(self, 'basic_ner_%s' % ner)
            category = method()
            if category:
                categories.append(category)
                _, percent = category
                if percent > 0.9:
                   break
        LABELS = [
            ('page-label', ('pàgina', 'pàg.', 'página', 'pág.', 'page',
                    'p.')),
            ('invoice_number-label', ('número de factura', 'número factura',
                    'núm. factura', 'núm. fra.', 'nº factura', 'factura nº',
                    'nº de factura', 'nº.factura', 'nº fra', 'nº fact', 'nº',
                    'factura', 'factura de cargo', 'nota de cargo',
                    'invoice number', 'invoice')),
            ('invoice_date-label', ('fecha factura', 'fecha', 'invoice date',
                'date')),
            ('email-label', ('correu electrònic', 'correu-e',
                    'correo electrónico', 'correo-e', 'e-mail', 'email')),
            ('url-label', ('pàgina web', 'web', 'url')),
            ('phone-label', ('telèfon', 'tel.', 't.', 'teléfono', 'telephone',
                    'phone', 't.')),
            ('fax-label', ('fax', 'fax.')),
            ('tax_identifer-label', ('n.i.f.', 'nif', 'c.i.f.', 'cif',
                    'tax identifier')),
            ('customer_code-label', ('client', 'cliente', 'customer')),
            ('payment_type-label', ('forma de pagament', 'forma de pago',
                    'payment type')),
            ('untaxed_amount-label', ('base imposable', 'base imp.',
                    'base imponible', 'untaxed amount')),
            ('total_amount-label', ('total factura', 'total', 'total fra.',
                    'total amount')),
            # Non-labels
            ('enterprise_type', ('s.l.', 'sl', 's.a.', 'sa', 's.c.c.l.',
                    'sccl', 's.c.p.', 'scp', 'inc.', 'inc', 'limited')),
            # Headers
            ('product_code-header', ('codi', 'código', 'code')),
            ('product_description-header', ('descripció', 'descripción')),
            ('quantity-header', ('quantitat', 'cantidad', 'quantity')),
            ('discount-header', ('descompte', 'dte.', 'descuento', 'dto.')),
            ('unit_price-header', ('preu unitari', 'preu unitat', 'preu un.',
                    'preu', 'precio unitario', 'precio unidad', 'precio un.'
                    'precio', 'unit price', 'price')),
            ('amount-header', ('import', 'importe', 'amount')),
            ]
        for item in LABELS:
            category = self.basic_ner_label(item[0], item[1])
            if category:
                categories.append(category)
                _, percent = category
                if percent > 0.95:
                    break
        self.categories = json.dumps(categories)


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

    def get_model_type_name(self, records):
        Model = Pool().get('ir.model')

        if self.model_type:
            t = TranslatedSelection('model_type')
            model_type = t.__get__(self, self)
        else:
            record = records[0]
            model, = Model.search([('model_name', '=', record.__name__)], limit=1)
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

    def scan_engines(self):
        super().scan_engines()
        yield 'text'
        if self.text and self.text.strip():
            yield 'textboxes'
        else:
            yield 'tesseract'

    def guess_sentences(self):
        pool = Pool()
        DocumentBox = pool.get('papyrus.document.box')

        new_boxes = []
        boxes = sorted([b for b in self.boxes if b.type == 'text'],
            key=lambda b: (b.y0, b.x0))
        while boxes:
            new_current_boxes = []
            box = boxes.pop(0)
            print('Looking for sentences of "%s"' % box.text)
            current_r = Rectangle(box)
            current_categories = json.loads(box.categories)
            # To find the next box in the line, we look no further than the
            # current bounding box + the length of the box's length.
            current_r.x1 += current_r.y1 - current_r.y0
            for ibox in boxes:
                if current_r.text.strip().endswith(':'):
                    break
                if not current_r.intersects(ibox):
                    continue

                new_box = DocumentBox()
                new_box.type = 'text'
                new_box.x0 = min(current_r.x0, ibox.x0)
                new_box.y0 = min(current_r.y0, ibox.y0)
                new_box.x1 = max(current_r.x1, ibox.x1)
                new_box.y1 = max(current_r.y1, ibox.y1)
                # TODO: This condition should not be necessary as we always
                # process the left-most box before the right one. Isn't it?
                if current_r.x0 < ibox.x0:
                    new_box.text = current_r.text + ' ' + ibox.text
                else:
                    new_box.text = ibox.text + ' ' + current_r.text
                new_box.basic_ner()
                new_box_categories = json.loads(new_box.categories)
                current_r = Rectangle(new_box)
                current_r.x1 += current_r.y1 - current_r.y0
                if not current_categories:
                    new_current_boxes.append(new_box)


            new_boxes += new_current_boxes

        self.boxes = self.boxes + tuple(new_boxes)

    def guess_boxes(self):
        counter = 0
        # Start with basic NER
        for box in self.boxes:
            counter += 1
            print('Checking "%s" (%d/%d)...' % (box.text, counter,
                    len(self.boxes)))
            box.basic_ner()
            print('Result: ', box.categories)

        self.save()
        # Now group boxes in the same line
        self.guess_sentences()

        # Now search for specific attributes
        date = None
        dates = []
        for box in self.boxes:
            categories = json.loads(box.categories)
            for category, probability in categories:
                if category == 'date':
                    dates.append(box)
        if len(dates) == 1:
            date = dates[0].text

        print('DATE: ', date)

    def on_change_with_image(self, name=None):
        import io
        from PIL import Image, ImageDraw

        image = super().on_change_with_image(name)
        if image:
            im = Image.open(io.BytesIO(image))
            draw = ImageDraw.Draw(im)
            xscale = 1.385
            yscale = 1.385
            GREEN = (0, 192, 192)
            #RED = (192, 0, 0)
            for box in self.boxes:
                categories = json.loads(box.categories)
                if not categories:
                    continue
                draw.rectangle(
                    (box.x0 * xscale, box.y0 * yscale,
                        box.x1 * xscale, box.y1 * yscale),
                    #fill=(0, 192, 192),
                    outline=GREEN)
            image = io.BytesIO()
            im.save(image, format='png')
            image = image.getvalue()
        return image

    def scan(self):
        super().scan()
        self.guess_boxes()
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
