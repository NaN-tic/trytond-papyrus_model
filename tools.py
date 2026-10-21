import base64
from decimal import Decimal
import json
import logging
from datetime import datetime
from magic import Magic
from sql.conditionals import Greatest
from sql.functions import Function, Upper
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.modules.widgets.tools import Similarity, create_similarity

logger = logging.getLogger(__name__)

CODE_SEPARATORS = '-‐‑‒–—− _./\\\t\r\n\u00a0'


class Replace(Function):
    __slots__ = ()
    _function = 'REPLACE'


def normalize_product_code(code):
    code = (code or '').upper()
    for separator in CODE_SEPARATORS:
        code = code.replace(separator, '')
    return code


def find_product_by_normalized_code(Line, party, lines, related_model,
        history_party):
    lines = [line for line in lines if not getattr(line, 'product', None)]
    codes = {
        normalize_product_code(getattr(line, name, None))
        for line in lines for name in ('product_code', 'external_code')
        } - {''}
    if not codes:
        return
    pool = Pool()
    Product = pool.get('product.product')

    def search_codes(Model, names, domain):
        table = Model.__table__()
        condition = None
        for name in names:
            column = Upper(getattr(table, name))
            for separator in CODE_SEPARATORS:
                column = Replace(column, separator, '')
            match = column.in_(sorted(codes))
            condition = match if condition is None else condition | match
        query = table.select(table.id, where=condition)
        return Model.search(domain + [('id', 'in', query)])

    by_code = {}
    for product in search_codes(Product, ['code'], []):
        code = normalize_product_code(product.code)
        by_code.setdefault(code, set()).add(product)

    related_by_code = {}
    try:
        Related = pool.get(related_model)
    except KeyError:
        Related = None
    if Related:
        domain = [('party', '=', party)]
        for record in search_codes(Related, ['code'], domain):
            products = ([record.product] if record.product
                else record.template.products)
            code = normalize_product_code(record.code)
            related_by_code.setdefault(code, set()).update(products)

    history_by_code = {}
    names = [name for name in ('product_code', 'external_code')
        if name in Line._fields]
    for record in search_codes(Line, names, [
            (history_party, '=', party),
            ('product', '!=', None)]):
        for name in names:
            code = normalize_product_code(getattr(record, name))
            if code in codes:
                history_by_code.setdefault(code, set()).add(record.product)

    for line in lines:
        for name in ('product_code', 'external_code'):
            code = normalize_product_code(getattr(line, name, None))
            sources = (related_by_code, by_code, history_by_code)
            candidates = next((source[code] for source in sources
                    if source.get(code)), set())
            if candidates:
                if len(candidates) == 1:
                    line.product, = candidates
                break


def convert_nulls(obj):
    'In some cases, x-ai/grok-4-fast will return ":null" instead of null'
    'Recursively convert ":null" to None in dicts and lists'
    if isinstance(obj, dict):
        return {k: convert_nulls(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_nulls(i) for i in obj]
    elif obj == ':null':
        return None
    else:
        return obj


class LLMError(Exception):
    pass


def find_party_by_similarity(text, role_domain=None, model_name='party.party',
        role_field=None, related_party_field='id', related_date_field=None,
        cutoff=None):
    pool = Pool()
    Model = pool.get(model_name)
    Party = pool.get('party.party')
    role_domain = role_domain or []
    table = Model.__table__()
    cursor = Transaction().connection.cursor()
    database = Transaction().database

    if not text:
        return None, 0

    create_similarity()
    text = text.strip()
    related_text_field = (
        'name' if model_name == 'party.party' else 'papyrus_name')
    extra_text_field = 'trade_name' if model_name == 'party.party' else None
    similarity = Similarity(
        Upper(database.unaccent(getattr(table, related_text_field))),
        Upper(database.unaccent(text)))
    if extra_text_field and hasattr(Model, extra_text_field):
        similarity = Greatest(similarity,
            Similarity(
                Upper(database.unaccent(getattr(table, extra_text_field))),
                Upper(database.unaccent(text))))

    where = similarity >= 0.4
    if related_date_field and cutoff:
        where &= getattr(table, related_date_field) >= cutoff.isoformat()
    if model_name == 'party.party':
        query = table.select(
            table.id, similarity,
            where=where,
            order_by=[similarity.desc, table.id.desc])
        cursor.execute(*query)
        for party_id, score in cursor.fetchall():
            parties = Party.search(role_domain + [('id', '=', party_id)],
                limit=1)
            if parties:
                return parties[0], float(score)
        return None, 0

    party_table = Party.__table__()
    join = table.join(
        party_table, condition=party_table.id == getattr(table,
            related_party_field))
    if role_field and role_field in Party._fields:
        where &= getattr(party_table, role_field) == True
    query = join.select(
        party_table.id, similarity,
        where=where,
        order_by=[similarity.desc]
        + ([getattr(table, related_date_field).desc]
            if related_date_field else [])
        + [table.id.desc],
        limit=1)
    cursor.execute(*query)
    row = cursor.fetchone()
    if not row:
        return None, 0
    party_id, score = row
    parties = Party.search(role_domain + [('id', '=', party_id)], limit=1)
    if not parties:
        return None, 0
    return parties[0], float(score)


def llm(messages, origin, model=None, pdf_engine=None, schema=None,
        max_tokens=None,
        referer='trytond', title=None):
    extra_body = {}
    has_file = False
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get('content')
        if not isinstance(content, list):
            continue
        if any(isinstance(part, dict) and part.get('type') == 'file'
                for part in content):
            has_file = True
            break
    if has_file:
        plugin = {'id': 'file-parser'}
        if pdf_engine in {'mistral-ocr', 'native', 'cloudflare-ai', 'pdf-text'}:
            plugin['pdf'] = {
                'engine': pdf_engine,
                }
        elif pdf_engine:
            logger.warning('Unsupported pdf engine %r, using provider default',
                pdf_engine)
        extra_body['plugins'] = [plugin]
    response_format = None
    if schema:
        response_format = {
            "type": "json_schema",
            "json_schema": schema
            }
    AIModel = Pool().get('ai.model')
    model = AIModel.get_or_create(model or 'openrouter/auto')
    response, error = model.get_completion(
        messages, origin,
        response_format=response_format, extra_body=extra_body or None,
        max_tokens=max_tokens)
    if error:
        raise LLMError(response)
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError):
        raise LLMError(f'Malformed OpenRouter response: {response!r}')

    if isinstance(content, list):
        content = ''.join([c.get("text", "") for c in content if isinstance(c, dict) and "text" in c])

    if not isinstance(content, str):
        logger.error(f'Response:\n{content}')
        raise LLMError(f"Unexpected message content format from assistant: {content}")

    try:
        return convert_nulls(json.loads(content))
    except json.JSONDecodeError as e:
        logger.error(f'Response:\n{content}')
        raise LLMError(f"Failed to parse JSON response: {e.msg}\nContent: {content}")

def to_url_data(binary, mimetype=None):
    if not mimetype:
        try:
            mimetype = Magic(mime=True).from_buffer(binary)
        except TypeError:
            mimetype = None
    b64 = base64.b64encode(binary).decode('utf-8')
    return f"data:{mimetype};base64,{b64}"


def to_date(value):
    if not value:
        return
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        print(f"Failed to parse date: {value}")
        return


def to_decimal(value, exp='0.000001'):
    if value is None:
        return None

    if isinstance(value, Decimal):
        res = value
    elif isinstance(value, (int, float)):
        # Use str to avoid binary float artifacts in Decimal conversion.
        res = Decimal(str(value))
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            res = Decimal(value)
        except Exception:
            return None
    else:
        return None

    return res.quantize(Decimal(exp))
