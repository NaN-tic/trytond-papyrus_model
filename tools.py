import base64
from decimal import Decimal
import json
import logging
import requests
from datetime import datetime
from magic import Magic

from trytond.config import config

logger = logging.getLogger(__name__)

API_KEY = config.get('openrouter', 'api_key')


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


def llm(messages, model=None, pdf_engine=None, schema=None, max_tokens=None,
        referer='trytond', title=None):

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": title,
        }
    payload = {
        "model": model or 'openrouter/auto',
        "messages": messages,
        }
    if max_tokens is not None:
        payload['max_tokens'] = max_tokens
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
        payload['plugins'] = [plugin]
    if schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": schema
            }

    p = json.dumps(payload)
    if len(p) > 2000:
        p = p[:1000] + '........' + p[-1000:]

    for retry in range(3):
        try:
            logger.debug('Sending to OpenRouter: %s', p)
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            logger.debug('Got response!')
            if response.status_code == 200:
                break
            if response.status_code == 500:
                logger.debug('Server error, retrying...')
                continue
            logger.error(f'OpenRouter error {response.status_code}: {response.text}')
            raise LLMError(f"OpenRouter error {response.status_code}: {response.text}")
        except requests.RequestException as e:
            logger.error(f'Error communicating with OpenRouter: {e}')
    else:
        raise LLMError("Failed to get a valid response from OpenRouter after retries.")

    try:
        data = response.json()
    except Exception:
        raise LLMError(f"Error converting to json server's response: {response.text}")

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise LLMError(f"Malformed OpenRouter response: {json.dumps(data)[:1000]}")

    logger.debug('Tokens consumed: %s', data.get('usage', {}))

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
