# This file is part papyrus module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
try:
    from trytond.modules.papyrus_model.tests.test_papyrus_model import suite
except ImportError:
    from .test_papyrus_model import suite

__all__ = ['suite']
