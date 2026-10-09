import json
import unittest
from decimal import ROUND_HALF_EVEN, Decimal
from unittest.mock import patch

from proteus import Model, config
from trytond.modules.account.tests.tools import create_chart, get_accounts
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestInvoiceAmountPrecision(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules(['papyrus_model', 'account_invoice'])
        create_company()
        company = get_company()
        create_chart(company)
        accounts = get_accounts(company)
        Party = Model.get('party.party')
        party = Party(name='Supplier', account_payable=accounts['payable'])
        party.save()
        Sequence = Model.get('ir.sequence')
        SequenceType = Model.get('ir.sequence.type')
        sequence_type, = SequenceType.find([
                ('name', '=', 'Papyrus Document')])
        sequence = Sequence(name='Document Sequence',
            sequence_type=sequence_type, company=company)
        sequence.save()
        Queue = Model.get('papyrus.queue')
        queue = Queue(name='Invoice Queue', type='document',
            model_type='invoice', company=company,
            document_sequence=sequence, source_directory='.',
            storage_directory='.', scheduler=False)
        queue.save()
        PapyrusDocument = Model.get('papyrus.document')
        document = PapyrusDocument(queue=queue, model_type='invoice')
        document.save()
        Invoice = Model.get('account.invoice')
        invoice = Invoice(type='in', party=party, document=document)
        invoice.save()

        data = {
            'invoice_number': '4104684356',
            'issue_date': '2026-10-09',
            'seller': {},
            'totals': {'subtotal': '65.470000', 'total': '79.224999'},
            'line_items': [{
                    'description': 'Extracted invoice item',
                    'quantity': '1',
                    'unit_price': '65.470000',
                    'line_total_excl_tax': '65.470000',
                    }],
            }
        configuration = config.get_config()
        with Transaction().start(configuration.database_name,
                configuration.user, context=configuration.context):
            pool = Pool()
            Currency = pool.get('currency.currency')
            Document = pool.get('papyrus.document')
            BackendInvoice = pool.get('account.invoice')
            backend_invoice = BackendInvoice(invoice.id)
            self.assertEqual(backend_invoice.currency.digits, 2)
            document = Document(document.id)
            document.extracted_data = json.dumps(data)

            # Reproduce a stored rounding factor with trailing zeros using
            # the actual currency rounding algorithm on every extracted amount.
            with patch.object(Currency, 'round', autospec=True,
                    side_effect=lambda currency, amount: Currency._round(
                        amount, Decimal('0.010000'), ROUND_HALF_EVEN)), \
                    patch.object(Document, 'guess_invoice_messages',
                        return_value=[]):
                document.guess_invoice()

            saved = BackendInvoice(invoice.id)
            self.assertEqual(saved.reference, '4104684356')
            self.assertEqual(saved.papyrus_total_amount, Decimal('79.22'))
            self.assertEqual(saved.papyrus_untaxed_amount, Decimal('65.47'))
            line, = saved.papyrus_lines
            self.assertEqual(line.amount, Decimal('65.47'))
            for amount in (saved.papyrus_total_amount,
                    saved.papyrus_untaxed_amount, line.amount):
                self.assertGreaterEqual(amount.as_tuple().exponent, -2)
