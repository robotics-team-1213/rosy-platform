"""A scripted Site Fleet hub socket for FleetAgent tests (D-419). Not a test module.

Like fleet/hub/server.py, it answers every message once and strictly in order: WELCOME
(or ACK when `welcome=False`) to HELLO; EVENT `{"accepted": true}` to EVENT (hub.py
`_event`), or ERROR `event_error`; and to HEARTBEAT either HEARTBEAT, ERROR
`heartbeat_error`, or nothing (`answer_heartbeats=False` / `answered_limit` — a silent
or broken hub, the only case where order is not preserved because a reply is missing).
Every reply goes through one ordered delay queue: a reply is released `delay` s after its
request but never before the reply to an earlier request.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core_common.protocol.schemas import Envelope, EnvelopeType


def envelope(kind: EnvelopeType, payload=None) -> str:
    return Envelope(type=kind, payload=payload or {}).model_dump_json()


class FakeHub:
    def __init__(self, *, welcome=True, answer_heartbeats=True, delay=0.0,
                 answered_limit=None, heartbeat_error=None, event_error=None) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[str] = []
        self.welcome = welcome
        self.answer_heartbeats = answer_heartbeats
        self.delay = delay
        self.answered_limit = answered_limit
        self.heartbeat_error = heartbeat_error
        self.event_error = event_error
        self.answered = 0
        self.aborted = False
        self.transport = SimpleNamespace(abort=self._abort)
        self._last_release = 0.0

    def _abort(self):
        self.aborted = True
        self.inbox.put_nowait(None)          # the reader's recv() fails like a dead socket

    def _reply(self, text: str, delay: float) -> None:
        loop = asyncio.get_running_loop()
        # Strictly increasing release times keep FIFO order even for equal delays.
        release = max(loop.time() + delay, self._last_release + 1e-6)
        self._last_release = release
        loop.call_at(release, self.inbox.put_nowait, text)

    async def send(self, text):
        if self.aborted:
            raise OSError("socket aborted")
        self.sent.append(text)
        env = Envelope.model_validate_json(text)
        if env.type is EnvelopeType.HELLO:
            kind = EnvelopeType.WELCOME if self.welcome else EnvelopeType.ACK
            self._reply(envelope(kind, {"last_event_seq": 0}), 0.0)
        elif env.type is EnvelopeType.EVENT:
            if self.event_error is not None:
                self._reply(envelope(EnvelopeType.ERROR, {
                    "code": self.event_error, "message": "scripted"}), self.delay)
            else:
                self._reply(envelope(EnvelopeType.EVENT, {"accepted": True}), self.delay)
        elif env.type is EnvelopeType.HEARTBEAT and self.answer_heartbeats:
            if self.answered_limit is None or self.answered < self.answered_limit:
                self.answered += 1
                if self.heartbeat_error is not None:
                    self._reply(envelope(EnvelopeType.ERROR, {
                        "code": self.heartbeat_error, "message": "scripted"}), self.delay)
                else:
                    self._reply(envelope(EnvelopeType.HEARTBEAT), self.delay)

    def events_sent(self) -> list[dict]:
        return [Envelope.model_validate_json(m).payload for m in self.sent
                if Envelope.model_validate_json(m).type is EnvelopeType.EVENT]

    async def recv(self):
        item = await self.inbox.get()
        if item is None:
            raise OSError("connection lost")
        return item

    async def close(self):
        self._abort()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False
