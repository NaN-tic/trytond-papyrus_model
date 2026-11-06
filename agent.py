from trytond.i18n import gettext
from trytond.model import fields
from trytond.model.modelstorage import AccessError
from trytond.modules.nantic_connection.chat_tools import (
    LLM_CONTENT_ATTACHMENT_DESCRIPTION)
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction


def get_papyrus_company_context(document_id, agent, company_ids=None):
    pool = Pool()
    User = pool.get('res.user')
    Document = pool.get('papyrus.document')
    transaction = Transaction()
    allowed = {company.id for company in agent.owner.companies}
    if company_ids is not None:
        allowed.intersection_update(company_ids)
    if transaction.user:
        allowed.intersection_update(
            company.id for company in User(transaction.user).companies)
    if not allowed:
        raise AccessError(gettext('papyrus_model.msg_papyrus_company_access'))
    with transaction.set_context(_companies=tuple(sorted(allowed))):
        company = Document(document_id).company
    if company and company.id not in allowed:
        raise AccessError(gettext('papyrus_model.msg_papyrus_company_access'))
    company_id = company.id if company else (
        agent.company.id if agent.company.id in allowed else min(allowed))
    context = {
        'company': company_id,
        'companies': [company_id] if company else sorted(allowed),
        '_companies': (company_id,) if company else tuple(sorted(allowed)),
        'company_filter': 'one' if company else 'all',
        'papyrus_company_ids': sorted(allowed),
        'employee': None,
        'warehouse': None,
        }
    with transaction.set_context(context):
        context['warehouse'] = agent.get_papyrus_company_warehouse(company_id)
    return context


class Agent(metaclass=PoolMeta):
    __name__ = 'nantic.agent'

    papyrus_multicompany = fields.Boolean('Shared Papyrus Inbox')

    def get_papyrus_company_warehouse(self, company_id):
        return None

    def get_run_context(self, **extra_context):
        context = super().get_run_context(**extra_context)
        if (self.papyrus_multicompany
                and context.get('current_model') == 'papyrus.document'
                and context.get('current_record')):
            context.update(get_papyrus_company_context(
                context['current_record'], self,
                context.get('papyrus_company_ids')))
        return context

    def get_conversation_message_metadata(self):
        metadata = super().get_conversation_message_metadata()
        context = Transaction().context
        if self.papyrus_multicompany and 'papyrus_company_ids' in context:
            metadata['papyrus_company_ids'] = context['papyrus_company_ids']
        return metadata

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


class AgentWarehouse(metaclass=PoolMeta):
    __name__ = 'nantic.agent'

    def get_papyrus_company_warehouse(self, company_id):
        User = Pool().get('res.user')
        warehouse = User(self.owner.id).get_company_warehouse(company_id)
        return warehouse.id if warehouse else None


class Conversation(metaclass=PoolMeta):
    __name__ = 'nantic.chat.conversation'

    def get_request_context(self):
        context = super().get_request_context()
        agent = self.get_active_agent()
        if not agent or not agent.papyrus_multicompany:
            return context
        reference = self.get_source_record_reference()
        if not reference or reference[0] != 'papyrus.document':
            return context
        for message in self.messages:
            metadata = message.metadata or {}
            if 'papyrus_company_ids' in metadata:
                company_ids = metadata['papyrus_company_ids']
                break
        else:
            company_ids = None
        context.update(get_papyrus_company_context(
            reference[1], agent, company_ids))
        return context
