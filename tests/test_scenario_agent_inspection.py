import json
import unittest

from proteus import Model
from trytond.exceptions import UserError
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestAgentInspection(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(
            ['papyrus_model', 'purchase', 'party_supplier'])

        create_company()
        company = get_company()

        supplier = Model.get('party.party')(name='Supplier')
        supplier.supplier = True
        supplier.save()

        purchase = Model.get('purchase.purchase')()
        purchase.company = company
        purchase.party = supplier
        purchase.save()

        Sequence = Model.get('ir.sequence')
        SequenceType = Model.get('ir.sequence.type')
        document_sequence_type, = SequenceType.find([
                ('name', '=', 'Papyrus Document')])
        document_sequence = Sequence(
            name='Document Sequence',
            sequence_type=document_sequence_type)
        document_sequence.save()

        queue = Model.get('papyrus.queue')()
        queue.type = 'document'
        queue.name = 'Purchase Queue'
        queue.source_directory = '/tmp'
        queue.storage_directory = '/tmp'
        queue.document_sequence = document_sequence
        queue.company = company
        queue.save()

        with Transaction().start(config.database_name, config.user):
            pool = Pool()
            Document = pool.get('papyrus.document')
            DbPurchase = pool.get('purchase.purchase')
            self.assertIn('mark_inspected', Document._buttons)

            document = Document(
                queue=pool.get('papyrus.queue')(queue.id))
            document.save()
            with self.assertRaises(UserError):
                Document.mark_inspected([document])
            self.assertEqual(Document(document.id).state, 'pending')

            Document.write([document], {
                    'company': company.id,
                    'model_type': 'purchase',
                    'extracted_data': '{}',
                    })
            with self.assertRaises(UserError):
                Document.mark_inspected([document])
            self.assertEqual(Document(document.id).state, 'pending')

            extracted_data = json.dumps({
                    'purchase_number': 'PUR-001',
                    'line_items': [],
                    })
            Document.write([document], {
                    'company': company.id,
                    'model_type': 'purchase',
                    'extracted_data': extracted_data,
                    })
            Document.mark_inspected([document])

            document = Document(document.id)
            self.assertEqual(document.state, 'inspected')
            self.assertEqual(document.extracted_data, extracted_data)
            self.assertFalse(document.purchase)

            DbPurchase.write([DbPurchase(purchase.id)], {
                    'document': document.id,
                    })
            document = Document(document.id)
            self.assertEqual(document.get_record().id, purchase.id)
