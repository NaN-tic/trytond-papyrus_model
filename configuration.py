# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelSingleton, ModelSQL, ModelView


class Configuration(ModelSingleton, ModelSQL, ModelView):
    __name__ = 'papyrus.configuration'
