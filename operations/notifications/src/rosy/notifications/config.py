"""Protected operator registration, never requester-selected destinations."""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from core_common.notification_channels import Channel


def https_url(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError('protected URLs require HTTPS without credentials or query')
    return value


@dataclass(frozen=True)
class Producer:
    identity: str
    token_sha256: str = field(repr=False)
    channels: frozenset[str]
    owner_url: str
    owner_token: str = field(repr=False)
    screen_url: str
    interval_s: int = 60
    max_attempts: int = 3
    ttl_s: int = 600
    capacity: int = 1000
    admissions_per_minute: int = 20

    def __post_init__(self):
        if self.identity not in ('fleet', 'harbor') or not re.fullmatch('[a-f0-9]{64}', self.token_sha256):
            raise ValueError('registered machine identity and SHA-256 required')
        if not self.channels or len(self.owner_token) < 32:
            raise ValueError('approved channels and separate owner credential required')
        if hashlib.sha256(self.owner_token.encode()).hexdigest() == self.token_sha256:
            raise ValueError('owner check and submission credentials must differ')
        for value in (self.owner_url, self.screen_url):
            https_url(value)
        for value, ceiling in ((self.interval_s, 3600), (self.max_attempts, 3), (self.ttl_s, 600),
                               (self.capacity, 1000), (self.admissions_per_minute, 20)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError('finite producer delivery budgets required')
        if self.interval_s < 60:
            raise ValueError('channel interval must be at least 60 seconds')
        if self.identity == 'fleet' and (self.interval_s, self.max_attempts, self.ttl_s) != (60, 3, 600):
            raise ValueError('Fleet D-661 profile is fixed')


def load(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    channels = {name: Channel(row['kind'], os.environ[row['endpoint_env']],
                              os.environ[row['chat_id_env']] if 'chat_id_env' in row else None)
                for name, row in data['channels'].items()}
    producers = {}
    for identity, row in data['producers'].items():
        if identity == 'harbor' and set(row['budget']) != {
                'interval_s', 'max_attempts', 'ttl_s', 'capacity', 'admissions_per_minute'}:
            raise ValueError('Harbor requires an explicitly selected delivery budget')
        token = os.environ[row['token_env']]
        if len(token) < 32:
            raise ValueError('machine credential requires at least 32 characters')
        producers[identity] = Producer(identity, hashlib.sha256(token.encode()).hexdigest(),
                                      frozenset(row['channels']), row['owner_url'],
                                      os.environ[row['owner_token_env']], row['screen_url'],
                                      **row['budget'])
    return channels, producers
