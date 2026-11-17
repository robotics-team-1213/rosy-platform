"""D-661 fixed-channel transport, shared without incident or ledger ownership."""

import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


class _RedactProviderURL(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        cleaned = re.sub(r'https://(?:discord\.com/api/webhooks/|hooks\.slack\.com/services/|api\.telegram\.org/bot)[^\s"\']+',
                         '[notification destination redacted]', message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


logging.getLogger('httpx').addFilter(_RedactProviderURL())


@dataclass(frozen=True)
class Channel:
    kind: str
    endpoint: str = field(repr=False)
    chat_id: str | int | None = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.endpoint, str):
            raise ValueError('invalid notification destination')
        patterns = {
            'discord': ('discord.com', r'/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+'),
            'slack': ('hooks.slack.com', r'/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+'),
            'telegram': ('api.telegram.org', r'/bot[0-9]+:[A-Za-z0-9_-]+/sendMessage'),
        }
        target = urlsplit(self.endpoint)
        expected = patterns.get(self.kind)
        if (expected is None or target.scheme != 'https' or target.netloc != expected[0]
                or target.query or target.fragment or not re.fullmatch(expected[1], target.path)
                or (self.kind == 'telegram' and (type(self.chat_id) not in (str, int)
                    or not re.fullmatch(r'-?[0-9]+|@[A-Za-z0-9_]+', str(self.chat_id))))):
            raise ValueError('invalid notification destination')

    @property
    def fingerprint(self):
        return hashlib.sha256((self.endpoint + '\0' + str(self.chat_id or '')).encode()).hexdigest()


async def send_channel(http, channel, text):
    """Only 429 and definite pre-connection failure permit another attempt."""
    payload = {'content': text, 'allowed_mentions': {'parse': []}, 'flags': 4}
    params = {'wait': 'true'} if channel.kind == 'discord' else None
    if channel.kind == 'slack':
        payload = {'text': text, 'blocks': [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}}],
                   'unfurl_links': False, 'unfurl_media': False}
    elif channel.kind == 'telegram':
        payload = {'chat_id': channel.chat_id, 'text': text, 'link_preview_options': {'is_disabled': True}}
    state, code, provider_id, retry_after = 'UNKNOWN', 'PROVIDER_OUTCOME_UNKNOWN', None, 60
    try:
        response = await http.post(channel.endpoint, json=payload, params=params, timeout=5, follow_redirects=False)
        if response.status_code == 429:
            state, code = 'RETRY', 'PROVIDER_RATE_LIMIT'
            delay = response.headers.get('Retry-After', '60')
            if channel.kind == 'telegram':
                delay = response.json().get('parameters', {}).get('retry_after', delay)
            try:
                delay = float(delay)
                retry_after = max(60, delay) if math.isfinite(delay) else 60
            except (ValueError, TypeError):
                pass
        elif response.status_code == 200:
            if channel.kind == 'slack' and response.text.strip() == 'ok':
                state, code = 'SENT', 'PROVIDER_ACCEPTED'
            elif channel.kind == 'discord':
                provider_id = response.json().get('id')
                if isinstance(provider_id, str) and re.fullmatch(r'[0-9]{1,32}', provider_id):
                    state, code = 'SENT', 'PROVIDER_ACCEPTED'
                else:
                    provider_id = None
            elif channel.kind == 'telegram':
                body = response.json()
                value = (body.get('result') or {}).get('message_id')
                if body.get('ok') is True and type(value) is int and value >= 0:
                    provider_id, state, code = str(value), 'SENT', 'PROVIDER_ACCEPTED'
        elif 400 <= response.status_code < 500:
            state, code = 'FAILED', 'PROVIDER_REFUSED'
    except (httpx.ConnectError, httpx.ConnectTimeout):
        state, code = 'RETRY', 'PROVIDER_UNREACHABLE'
    except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
        pass
    return state, code, provider_id, retry_after
