import json
import unittest

from proteus import Model
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(
            ['papyrus_model', 'purchase', 'party_supplier'])

        _ = create_company()
        company = get_company()

        Party = Model.get('party.party')
        supplier = Party(name='Acme Supplier')
        supplier.supplier = True
        supplier.save()

        Purchase = Model.get('purchase.purchase')
        existing_purchase = Purchase()
        existing_purchase.company = company
        existing_purchase.party = supplier
        existing_purchase.reference = 'SUP-PO-001'
        existing_purchase.save()

        inverse_purchase = Purchase()
        inverse_purchase.company = company
        inverse_purchase.party = supplier
        inverse_purchase.reference = 'SUP-PO-002'
        inverse_purchase.save()

        Sequence = Model.get('ir.sequence')
        SequenceType = Model.get('ir.sequence.type')
        document_sequence_type, = SequenceType.find([
                ('name', '=', 'Papyrus Document')])
        document_sequence = Sequence(
            name='Document Sequence',
            sequence_type=document_sequence_type)
        document_sequence.save()

        Queue = Model.get('papyrus.queue')
        queue = Queue()
        queue.type = 'document'
        queue.name = 'Purchase Queue'
        queue.source_directory = '/tmp'
        queue.storage_directory = '/tmp'
        queue.document_sequence = document_sequence
        queue.company = company
        queue.save()

        with Transaction().start(
                config.database_name, config.user) as transaction:
            pool = Pool()
            Document = pool.get('papyrus.document')
            DbPurchase = pool.get('purchase.purchase')
            db_queue = pool.get('papyrus.queue')(queue.id)
            db_company = pool.get('company.company')(company.id)
            DbPurchase.write([DbPurchase(existing_purchase.id)], {
                    'number': 'PUR-001',
                    })
            DbPurchase.write([DbPurchase(inverse_purchase.id)], {
                    'number': 'PUR-002',
                    })

            # (a) The supplier confirmation references an existing,
            # unlinked purchase: it gets linked instead of a new one being
            # created.
            document = Document()
            document.queue = db_queue
            document.company = db_company
            document.model_type = 'purchase'
            document.extracted_data = json.dumps({
                    'purchase_number': 'PUR-001',
                    'purchase_reference': 'SUP-PO-001',
                    'issue_date': '2024-01-01',
                    'seller': {'name': 'Acme Supplier'},
                    'line_items': [],
                    })
            document.save()
            document.guess_purchase()

            document = Document(document.id)
            self.assertEqual(len(document.purchase), 1)
            self.assertEqual(document.purchase[0].id, existing_purchase.id)
            self.assertEqual(DbPurchase.search_count([]), 2)

            # (b) If the extractor swaps the internal number and supplier
            # reference, Papyrus finds the purchase with the inverse lookup.
            inverse_document = Document()
            inverse_document.queue = db_queue
            inverse_document.company = db_company
            inverse_document.model_type = 'purchase'
            inverse_document.extracted_data = json.dumps({
                    'purchase_number': 'SUP-PO-002',
                    'purchase_reference': 'PUR-002',
                    'issue_date': '2024-01-02',
                    'seller': {'name': 'Acme Supplier'},
                    'line_items': [],
                    })
            inverse_document.save()
            inverse_document.guess_purchase()

            inverse_document = Document(inverse_document.id)
            self.assertEqual(len(inverse_document.purchase), 1)
            self.assertEqual(inverse_document.purchase[0].id,
                inverse_purchase.id)
            self.assertEqual(DbPurchase.search_count([]), 2)

            # (c) No existing purchase matches the supplier's reference: a
            # new purchase is created, as before.
            other_document = Document()
            other_document.queue = db_queue
            other_document.company = db_company
            other_document.model_type = 'purchase'
            other_document.extracted_data = json.dumps({
                    'purchase_number': 'PUR-999',
                    'purchase_reference': 'SUP-PO-999',
                    'issue_date': '2024-01-03',
                    'seller': {'name': 'Acme Supplier'},
                    'line_items': [],
                    })
            other_document.save()
            other_document.guess_purchase()

            other_document = Document(other_document.id)
            self.assertEqual(len(other_document.purchase), 1)
            new_purchase = other_document.purchase[0]
            self.assertNotEqual(new_purchase.id, existing_purchase.id)
            self.assertEqual(new_purchase.reference, 'SUP-PO-999')
            self.assertEqual(DbPurchase.search_count([]), 3)

            transaction.commit()
