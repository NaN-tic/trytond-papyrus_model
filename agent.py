from trytond.i18n import gettext
from trytond.model.modelstorage import AccessError
from trytond.modules.nantic_connection.chat_tools import (
    LLM_CONTENT_ATTACHMENT_DESCRIPTION)
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction


class Agent(metaclass=PoolMeta):
    __name__ = 'nantic.agent'

    def create_conversation(self, action_summary, now):
        conversation = super().create_conversation(action_summary, now)
        context = Transaction().context
        if (context.get('current_model') == 'papyrus.document'
                and context.get('current_record')):
            Document = Pool().get('papyrus.document')
            document = Document(context['current_record'])
            if (document.document_company
                    and document.document_company not in self.owner.companies):
                raise AccessError(gettext('ir.msg_access_rule_error',
                    **Document.__names__()))
            data = document.data
            if data:
                conversation.add_message({
                    'content': 'The Papyrus source document is attached.',
                    'metadata': self.get_conversation_message_metadata(),
                    'attachments': [{
                        'name': document.filename or 'document.pdf',
                        'data': data,
                        'description': LLM_CONTENT_ATTACHMENT_DESCRIPTION,
                        }],
                    }, 'user')
        return conversation

    @classmethod
    def trigger_run(cls, records, trigger):
        if trigger.model.name == 'papyrus.document':
            for record in records:
                super().trigger_run([record], trigger)
        else:
            super().trigger_run(records, trigger)
