from lxml import etree, html

from trytond.i18n import gettext
from trytond.model import fields
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
            Pool().get('nantic.chat.conversation').write(
                [conversation], {'papyrus_document': document.id})
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


class Conversation(metaclass=PoolMeta):
    __name__ = 'nantic.chat.conversation'

    papyrus_document = fields.Many2One(
        'papyrus.document', 'Papyrus Document', readonly=True,
        ondelete='SET NULL')


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'

    inspection_history = fields.Function(fields.Binary(
            'Inspection Conversations', filename='inspection_history_filename'),
        'get_inspection_history')
    inspection_history_filename = fields.Function(
        fields.Char('Inspection History Filename'), 'get_inspection_history')

    def get_inspection_history(self, name):
        if name == 'inspection_history_filename':
            return 'inspection-history.html'
        Conversation = Pool().get('nantic.chat.conversation')
        conversations = Conversation.search([
            ('papyrus_document', '=', self.id),
            ('creation_origin', 'in', ['trigger', 'invocation', 'cron']),
            ], order=[('id', 'ASC')])
        if not conversations:
            return None
        history = html.document_fromstring(
            '<html><head><meta charset="utf-8"></head>'
            '<body style="font-family: sans"></body></html>')
        for conversation in conversations:
            section = etree.SubElement(history.find('body'), 'section')
            etree.SubElement(section, 'h1').text = conversation.title
            section.extend(html.document_fromstring(
                conversation.get_conversation()).find('body'))
        return etree.tostring(history, method='html', encoding='utf-8',
            doctype='<!DOCTYPE html>')
