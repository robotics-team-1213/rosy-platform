"""Bounded delivery with a producer-owned, last-moment validity check."""

import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from core_common.notification_channels import send_channel
from core_common.protocol.notification_delivery import DeliveryOwnerReply, DeliveryRequest
from .journal import DeliveryError


class HttpOwnerCheck:
    def __init__(self, http):
        self.http = http

    async def __call__(self, profile, request):
        try:
            response = await self.http.post(profile.owner_url, json=request.model_dump(),
                                            headers={'Authorization': 'Bearer ' + profile.owner_token},
                                            timeout=3, follow_redirects=False)
            if response.status_code != 200:
                return None
            reply = DeliveryOwnerReply.model_validate(response.json())
            if (reply.notification_id, reply.revision) != (request.notification_id, request.revision):
                return None
            return reply.valid
        except (httpx.HTTPError, ValueError, OSError):
            return None


class DeliveryService:
    def __init__(self, journal, channels, producers, http, *, owner_check=None, clock=time.time):
        if (not producers or len(producers) > 2 or len(channels) > 8
                or any(channel.kind != 'telegram' and channel.chat_id is not None for channel in channels.values())
                or any(key != profile.identity or not profile.channels <= channels.keys()
                       for key, profile in producers.items())
                or len({p.token_sha256 for p in producers.values()}) != len(producers)
                or len({channel.fingerprint for channel in channels.values()}) != len(channels)):
            raise ValueError('distinct registered machines and approved channel mappings required')
        self.journal, self.channels, self.producers = journal, dict(channels), dict(producers)
        self.http, self.owner_check, self.clock = http, owner_check or HttpOwnerCheck(http), clock
        self._worker = asyncio.Lock()
        self._turn = 0

    def authenticate(self, authorization):
        if not authorization.startswith('Bearer ') or not 32 <= len(authorization[7:]) <= 512:
            raise DeliveryError(401, 'MACHINE_CREDENTIAL_REQUIRED')
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        for profile in self.producers.values():
            if hmac.compare_digest(profile.token_sha256, digest):
                return profile
        raise DeliveryError(401, 'MACHINE_CREDENTIAL_REQUIRED')

    def accept(self, request, profile):
        if request.producer != profile.identity or request.channel not in profile.channels:
            raise DeliveryError(403, 'PRODUCER_CHANNEL_FORBIDDEN')
        return self.journal.accept(request, profile, self.channels[request.channel].fingerprint, self.clock())

    async def run_once(self):
        async with self._worker:
            profiles = list(self.producers.values())
            start = self._turn % len(profiles)
            self._turn += 1
            for profile in profiles[start:] + profiles[:start]:
                row = self.journal.claim(profile.identity, self.clock())
                if row is not None:
                    await self._deliver(profile, row)

    async def _deliver(self, profile, row):
        request = DeliveryRequest.model_validate_json(row['body'])
        channel = self.channels.get(request.channel)
        if request.channel not in profile.channels or channel is None or channel.fingerprint != row['route_hash']:
            self.journal.finish(row, 'SUPERSEDED', self.clock())
            return
        try:
            try:
                valid = await asyncio.wait_for(self.owner_check(profile, request), timeout=3)
            except Exception:
                valid = None
            if self.clock() >= request.expires_at:
                self.journal.finish(row, 'EXPIRED', self.clock())
                return
            if valid is not True:
                self.journal.finish(row, 'SUPERSEDED' if valid is False else 'PENDING', self.clock(), delay=1)
                return
            if row['attempts'] >= profile.max_attempts:
                self.journal.finish(row, 'FAILED', self.clock())
                return
            if not self.journal.start_attempt(row, profile, self.clock()):
                self.journal.finish(row, 'PENDING', self.clock(), delay=1)
                return
            # No await after the owner reply and before entry to the fixed-channel transport.
            link = profile.screen_url + '?' + urlencode({'subject': request.subject_id,
                                                         'occurrence': request.occurrence_id})
            text = (f'ROSY {request.kind} · {request.classification}\n'
                    f'{request.subject_id} · {request.occurrence_id}\n'
                    f'{request.observed_at} · {request.expires_at}\n{link}')
            if self.clock() >= request.expires_at:
                self.journal.finish(row, 'EXPIRED', self.clock())
                return
            state, _code, _provider_id, delay = await send_channel(self.http, channel, text)
            if state == 'RETRY' and (row['attempts'] >= profile.max_attempts
                                     or self.clock() + delay >= request.expires_at):
                state = 'FAILED'
            self.journal.finish(row, state, self.clock(), delay)
        except BaseException:
            self.journal.finish(row, 'UNKNOWN', self.clock())
            raise
