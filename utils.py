import re
import stdnum
import ngram
from datetime import datetime
from trytond.pool import Pool
from trytond.cache import Cache

NUMBER_SET = set('0123456789')
LABELS = [
    ('page-label', ('pàgina', 'pàg.', 'página', 'pág.', 'pag', 'page',
            'p.', 'página / page')),
    ('invoice_number-label', ('número de factura', 'número factura', 'número',
            'núm. factura', 'núm. fra.', 'nº factura', 'factura nº',
            'factura num.', 'factura no.', 'nº de factura', 'nº.factura',
            'nº fra', 'nº fact', 'nº:', 'nº', 'factura', 'factura nº',
            'factura de cargo', 'nota de cargo', 'invoice number', 'invoice')),
    ('invoice_date-label', ('data', 'fecha factura', 'fecha fra.', 'fecha fra',
            'fecha', 'fecha:', 'invoice date', 'date')),
    ('email-label', ('correu electrònic', 'correu-e',
            'correo electrónico', 'correo-e', 'e-mail', 'email')),
    ('url-label', ('pàgina web', 'web', 'url')),
    ('phone-label', ('telèfon', 'tel.', 't.', 'teléfono', 'telephone',
            'phone', 't.')),
    ('fax-label', ('fax', 'fax.')),
    ('tax_identifer-label', ('n.i.f.', 'nif', 'c.i.f.', 'cif', 'cif/nif',
            'nif / vat', 'tax identifier')),
    ('customer_code-label', ('client', 'cod.cliente', 'cliente nº',
            'nr. de cliente', 'nº cliente', 'cliente', 'cliente:',
            'número del cliente:', 'customer')),
    ('payment_type-label', ('forma de pagament', 'forma de pago',
            'payment type')),
    ('untaxed_amount-label', ('base imposable', 'base imp.',
            'base imponible', 'untaxed amount')),
    ('total_amount-label', ('total factura', 'total factura (eur)', 'total',
            'total fra.', 'total (eur)', 'total a pagar', 'total amount')),
    ('due_date-label', ('data de venciment', 'data venciment', 'venciment',
            'fecha de vencimiento', 'fecha vencimiento', 'fecha vto.',
            'vencimiento', 'due date', 'maturity date')),
    ('order-label', ('comanda', 'comanda:', 'su pedido', 'su pedido:')),
    ('shipment-label', ('albarà', 'albarán', 'nº albarán')),
    # Non-labels
    ('enterprise_type', ('s.l.', 'sl', 's.a.', 'sa', 's.c.c.l.',
            'sccl', 's.c.p.', 'scp', 'inc.', 'inc', 'limited')),
    # Headers
    ('product_code-header', ('codi', 'código', 'code')),
    ('product_description-header', ('descripció', 'descripción', 'concepte',
            'concepto')),
    ('quantity-header', ('quantitat', 'cantidad', 'quantity')),
    ('discount-header', ('descompte', 'dte.', 'descuento', 'dto.')),
    ('unit_price-header', ('preu unitari', 'preu unitat', 'preu unit.',
            'preu un.', 'preu', 'precio unitario', 'precio unidad',
            'precio unit.', 'precio un.' 'precio', 'unit price', 'price')),
    ('amount-header', ('import', 'total', 'importe', 'amount')),
    ]

class Rectangle:
    _caches = Cache('papyrus.document.box')

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
        self.categories = []
        self.children = []
        self.main_category = None
        self.main_weight = 0.0
        self.check()

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def width(self):
        return self.x1 - self.x0

    def __str__(self):
        return 'Rectangle(%.3f, %.3f, %.3f, %.3f, "%s")' % (self.x0, self.y0,
            self.x1, self.y1, self.text)

    def __repr__(self):
        #return 'Rectangle(%.3f, %.3f, %.3f, %.3f, "%s")' % (self.x0, self.y0,
            #self.x1, self.y1, self.text)
        return '"%s" (%s)' % (self.text, self.main_category)

    def has_a_number(self):
        if set('0123456789') & set(self.text):
            return True
        return False

    def is_number(self):
        text = self.text.replace('.', '').replace(',', '')
        try:
            float(text)
            return True
        except ValueError:
            return False

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

    def combine(self, *args):
        'Combine multiple rectangles (they should be sorted) and return a new'
        'rectangle'
        self.check()
        new = Rectangle(self)
        new.children.append(self)
        for other in args:
            new.children.append(other)
            new.x0 = min(new.x0, other.x0)
            new.y0 = min(new.y0, other.y0)
            new.x1 = max(new.x1, other.x1)
            new.y1 = max(new.y1, other.y1)
            if new.x0 < other.x0:
                new.text = new.text + ' ' + other.text
            else:
                new.text = other.text + ' ' + new.text
        return new

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
                or text.startswith('cl.') or text.startswith('calle')):
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

    def basic_ner_party(self):
        pool = Pool()
        Party = pool.get('party.party')

        names = self._caches.get('party-names', [])
        trade_names = self._caches.get('party-trade_names', [])
        if not names and not trade_names:
            parties = Party.search([])
            for party in parties:
                name = party.name and party.name.strip()
                if name:
                    names.append(name.lower())
                if hasattr(Party, 'trade_name'):
                    trade_name = party.trade_name and party.trade_name.strip()
                    if trade_name:
                        trade_names.append(trade_name.lower())
            self._caches.set('party-names', names)
            self._caches.set('party-trade_names', trade_names)

        stripped = self.text.strip().lower()
        if stripped in names + trade_names:
            return 'party', 0.9

        for suffix in ('s.l.', 'sl', 's.a.', 'sa', 's.a.u.', 's.c.c.l.',
                's.c.c.l', 'sccl', 's.c.p.', 'scp', 'inc.', 'inc', 'limited'):
            if stripped.endswith(suffix):
                return 'party', 0.7

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



        date = parse_date(self.text.strip().lower())
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
        text = text.replace('-', '').replace('.', '')
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
        stripped = self.text.strip()
        if stdnum.bic.is_valid(stripped):
            # There are lots of false positives with words such as 'CANTIDAD'
            # or 'FERNANDO', so we cannot assign a high probability
            # https://www.theswiftcodes.com/romania/bacxrobu/
            g = self._caches.get('country-codes')
            if not g:
                Country = Pool().get('country.country')
                g = [x.code.lower() for x in Country.search([])]
                self._caches.set('country-codes', g)
            country = stripped[4:6].lower()
            if not country in g:
                return
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
        self.categories = []
        for ner in ('zip', 'integer', 'float', 'city', 'subdivision',
                'country', 'street', 'date', 'phone', 'email', 'url', 'page',
                'currency', 'bic', 'iban', 'payment_type', 'payment_term',
                'tax_identifier', 'party'):
            method = getattr(self, 'basic_ner_%s' % ner)
            category = method()
            if category:
                self.categories.append(category)
                _, weight = category
                if weight > 0.9:
                   break
        else:
            for item in LABELS:
                category = self.basic_ner_label(item[0], item[1])
                if category:
                    self.categories.append(category)
                    _, weight = category
                    if weight > 0.95:
                        break
        self.compute_main_category()

    def compute_main_category(self):
        self.main_category = None
        self.main_weight = 0.0
        for category, weight in self.categories:
            if weight > self.main_weight:
                self.main_category = category
                self.main_weight = weight


class Sentencer:
    def __init__(self, box, boxes):
        'boxes should be sorted and of type "text".'
        self.box = box
        self.boxes = boxes
        self.max_sentence = []
        self.compute_max_sentence()

    def compute_max_sentence(self):
        def make_thinner(box):
            # In some cases bounding boxes for words in two separate lines
            # overlap So we make height 30% thinner. Experience shows that
            # reducing it 20% is not enough
            height = box.height
            box.y0 += height * 0.15
            box.y1 -= height * 0.15

        current = Rectangle(self.box)
        current.x1 += current.height
        make_thinner(current)
        self.max_sentence = []
        for box in self.boxes:
            if not current.intersects(box):
                continue
            self.max_sentence.append(box)
            current = current.combine(box)
            current.x1 += current.height
            make_thinner(current)
            if current.text.strip().endswith(':'):
                break

    def combinations(self, boxes=None):
        if boxes is None:
            boxes = self.max_sentence
        if len(boxes) == 1:
            return [boxes]
        if len(boxes) >= 5:
            box = boxes[0]
            box = box.combine(*boxes[1:])
            return [[box]]
        first = boxes[0]
        remaining = self.combinations(boxes[1:])
        res = []
        for children in remaining:
            res.append([first] + children)
            res.append([first.combine(children[0])] + children[1:])
        assert len(res) == 2 ** (len(boxes) - 1)
        return res


if __name__ == '__main__':
    boxes = []
    boxes.append(Rectangle(48, 194.282, 64.228, 203.943, 'NaN'))
    boxes.append(Rectangle(66.266, 194.282, 100.856, 203.943, 'Projectes'))
    boxes.append(Rectangle(102.894, 194.282, 111.903, 203.943, 'de'))
    boxes.append(Rectangle(113.94, 194.282, 154.851, 203.943, 'Programari'))
    boxes.append(Rectangle(156.889, 194.282, 178.609, 203.943, 'Lliure,'))
    boxes.append(Rectangle(180.647, 194.282, 194.317, 203.943, 'S.L.'))

    first = boxes[0]
    sentencer = Sentencer(first, boxes)
    for combination in sentencer.combinations():
        print(combination)
