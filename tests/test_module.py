
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.tests.test_tryton import ModuleTestCase
from trytond.modules.papyrus.tests import PapyrusCompanyTestMixin


class PapyrusModelTestCase(PapyrusCompanyTestMixin, ModuleTestCase):
    'Test PapyrusModel module'
    module = 'papyrus_model'
    extras = ['account_invoice', 'sale', 'stock']


del ModuleTestCase
