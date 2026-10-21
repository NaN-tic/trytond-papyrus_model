import unittest
from decimal import Decimal
from unittest.mock import patch

from proteus import Model, config
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestShipmentPurchaseMatching(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules(['papyrus_model', 'purchase'])
        create_company()
        company = get_company()
        Party = Model.get('party.party')
        party = Party(name='Supplier')
        party.save()
        Uom = Model.get('product.uom')
        unit, = Uom.find([('name', '=', 'Unit')])
        Template = Model.get('product.template')
        template = Template(name='Item', code='ITEM', type='goods',
            default_uom=unit, purchase_uom=unit, purchasable=True)
        template.save()
        product, = template.products
        Location = Model.get('stock.location')
        warehouse, = Location.find([('type', '=', 'warehouse')])
        Purchase = Model.get('purchase.purchase')
        Move = Model.get('stock.move')
        purchase_references = ('ORDER-ONE', 'ORDER-TWO')
        purchase_numbers = []
        moves = []
        for reference in purchase_references:
            purchase = Purchase(party=party, warehouse=warehouse,
                reference=reference)
            purchase.lines.new(product=product, quantity=2,
                unit_price=Decimal('10'))
            purchase.save()
            Model.get('res.user.warning').skip(
                f'papyrus_missing_purchase_lines.{purchase.id}',
                config.get_config().context)
            purchase.click('quote')
            purchase_numbers.append(purchase.number)
            move = Move(product=product, unit=unit, quantity=2,
                from_location=party.supplier_location,
                to_location=warehouse.input_location,
                origin=purchase.lines[0], currency=company.currency,
                unit_price=Decimal('10'))
            move.save()
            moves.append(move)
        Shipment = Model.get('stock.shipment.in')
        shipment = Shipment(supplier=party, warehouse=warehouse)
        shipment.save()
        SequenceType = Model.get('ir.sequence.type')
        sequence_type, = SequenceType.find([
                ('name', '=', 'Papyrus Document')])
        Sequence = Model.get('ir.sequence')
        sequence = Sequence(name='Documents', sequence_type=sequence_type)
        sequence.save()
        Queue = Model.get('papyrus.queue')
        queue = Queue(name='Shipments', type='document',
            source_type='directory', source_directory='/unused',
            storage_directory='/unused', document_sequence=sequence)
        queue.save()
        ProteusDocument = Model.get('papyrus.document')
        document = ProteusDocument(queue=queue, company=company,
            model_type='shipment_in')
        document.save()

        configuration = config.get_config()
        with Transaction().start(configuration.database_name,
                configuration.user, context=configuration.context):
            pool = Pool()
            Line = pool.get('papyrus.shipment.in.line')
            BackendShipment = pool.get('stock.shipment.in')
            BackendMove = pool.get('stock.move')
            Document = pool.get('papyrus.document')
            shipment = BackendShipment(shipment.id)
            schema = Document().guess_shipment_in_schema()
            items = schema['schema']['properties']['line_items']['items']
            self.assertIn('purchase_number', items['properties'])
            self.assertIn('purchase_number', items['required'])
            self.assertIn('null', items['properties']['unit_price']['type'])
            lines = [Line.build({
                        'product_code': 'ITEM', 'purchase_number': number,
                        'quantity': 2, 'unit_price': 10})
                for number in purchase_numbers]
            Line.find_product(party.id, lines)
            Line.find_move(shipment, lines, {
                    'purchase_number': 'ORDER-ONE; ORDER-TWO'})
            self.assertEqual([line.move.id for line in lines],
                [move.id for move in moves])
            for line in lines:
                line.shipment = shipment
            Line.save(lines)
            saved = Line(lines[0].id)
            self.assertEqual(saved.purchase_number, purchase_numbers[0])

            lines[0].purchase_number = None
            lines[0].move = None
            lines[0].external_code = 'REF-ONE'
            lines[0].description = 'Manually corrected description'
            lines[1].purchase_number = 'ORDER-TWO'
            lines[1].external_code = 'REF-TWO'
            duplicates = [Line.build({
                        'product_code': 'DUPLICATE', 'party_product_code': 'DUP',
                        'quantity': 2, 'unit_price': 10}) for _ in range(2)]
            for line in duplicates:
                line.shipment = shipment
            Line.save(lines + duplicates)
            shipment.document = Document(document.id)
            shipment.save()
            extracted = {
                'shipment_number': 'DELIVERY', 'issue_date': None,
                'seller': {'name': 'Supplier'},
                'line_items': [
                    {'product_code': 'ITEM', 'party_product_code': 'REF-TWO',
                        'quantity': 2, 'unit_price': 10,
                        'purchase_number': 'ORDER-ONE'},
                    {'product_code': 'ITEM', 'party_product_code': 'REF-ONE',
                        'quantity': 2, 'unit_price': 99,
                        'description': 'Extracted description',
                        'purchase_number': 'ORDER-ONE'},
                    {'product_code': 'DUPLICATE', 'party_product_code': 'DUP',
                        'quantity': 2, 'unit_price': 10,
                        'purchase_number': 'ORDER-ONE'},
                    {'product_code': 'DUPLICATE', 'party_product_code': 'DUP',
                        'quantity': 2, 'unit_price': 10,
                        'purchase_number': 'ORDER-TWO'},
                    ]}
            with Transaction().set_context(papyrus_reinspect=True), \
                    patch.object(Document, 'guess_shipment_in_messages',
                        return_value=[]), \
                    patch.object(Document, 'extract_data_with_llm',
                        return_value=extracted):
                Document(document.id).guess_shipment_in()
            reinspected = BackendShipment(shipment.id).papyrus_lines
            by_external = {line.external_code: line for line in reinspected}
            self.assertEqual(by_external['REF-ONE'].id, lines[0].id)
            self.assertEqual(by_external['REF-ONE'].purchase_number, 'ORDER-ONE')
            self.assertEqual(by_external['REF-ONE'].move.id, moves[0].id)
            self.assertEqual(by_external['REF-ONE'].description,
                'Manually corrected description')
            self.assertEqual(by_external['REF-ONE'].product.id, product.id)
            self.assertEqual(by_external['REF-ONE'].unit_price, Decimal('10'))
            self.assertEqual(by_external['REF-ONE'].quantity, Decimal('2'))
            self.assertEqual(by_external['REF-TWO'].purchase_number, 'ORDER-TWO')
            self.assertEqual(by_external['REF-TWO'].move.id, moves[1].id)
            self.assertTrue(all(line.purchase_number is None
                for line in reinspected if line.external_code == 'DUP'))

            payload = {'product_code': 'ITEM', 'quantity': 2, 'unit_price': 10}
            line = Line.build(payload)
            self.assertIsNone(line.purchase_number)
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {})
            self.assertIsNone(getattr(line, 'move', None))
            Line.find_move(shipment, [line], {'purchase_number': 'ORDER-ONE'})
            self.assertEqual(line.move.id, moves[0].id)

            line = Line.build(payload)
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {
                    'purchase_reference': 'ORDER-TWO'})
            self.assertEqual(line.move.id, moves[1].id)

            line = Line.build(dict(payload, purchase_number='MISSING'))
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {'purchase_number': 'ORDER-ONE'})
            self.assertIsNone(getattr(line, 'move', None))
            line = Line.build(payload)
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {'purchase_number': 'MISSING'})
            self.assertIsNone(getattr(line, 'move', None))

            lines = [Line.build(dict(payload, purchase_number='ORDER-ONE'))
                for _ in range(2)]
            Line.find_product(party.id, lines)
            Line.find_move(shipment, lines, {})
            self.assertTrue(all(getattr(line, 'move', None) is None
                for line in lines))
            lines[0].move = BackendMove(moves[0].id)
            Line.find_move(shipment, lines, {})
            self.assertEqual(lines[0].move.id, moves[0].id)
            self.assertIsNone(getattr(lines[1], 'move', None))

            BackendMove.write([BackendMove(moves[0].id)],
                {'unit_price': Decimal(0)})
            line = Line.build(dict(payload, purchase_number='ORDER-ONE'))
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {})
            self.assertIsNone(getattr(line, 'move', None))
            line.unit_price = Decimal(0)
            Line.find_move(shipment, [line], {})
            self.assertEqual(line.move.id, moves[0].id)
            line = Line.build(dict(payload, purchase_number='ORDER-ONE',
                    unit_price=None))
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {})
            self.assertEqual(line.move.id, moves[0].id)
            self.assertIsNone(line.unit_price)

            BackendMove.copy([BackendMove(moves[1].id)])
            line = Line.build(dict(payload, purchase_number='ORDER-TWO',
                    quantity=4))
            Line.find_product(party.id, [line])
            Line.find_move(shipment, [line], {})
            self.assertIsNone(getattr(line, 'move', None))
