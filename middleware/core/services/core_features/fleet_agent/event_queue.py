import asyncio
import logging

from core_common.protocol.schemas import Envelope, EnvelopeType

logger = logging.getLogger("fleet_agent")

#: Hub ERROR codes that mean this session is not (or no longer) paired: the session is
#: dropped at once (fleet/hub/hub.py `_error` sites; API Ref §3 `PAIRING_INVALID`). Any
#: other ERROR answering a heartbeat — e.g. TASK_PROJECTION_UNAVAILABLE from a hub with
#: one poisoned event row — still proves the hub is alive (D-419 round 3).
SESSION_FATAL_ERRORS = frozenset({
    "PAIRING_INVALID", "SESSION_NOT_PAIRED", "DUPLICATE_IDENTITY", "IDENTITY_DRIFT",
    "PROTOCOL_UNSUPPORTED",
})
#: A degraded hub answers every heartbeat with the same ERROR; log it this often.
DEGRADED_LOG_INTERVAL_S = 60.0
#: Hub codes that refuse an event for good (its content is outside the audit contract).
#: Every other ERROR to an event is treated as transient and re-sent, at most
#: EVENT_MAX_TRIES times in total, then dropped with a log line (D-407 review M3).
#: PAYLOAD_INVALID: the same bytes fail validation again, so re-sending cannot help.
PERMANENT_EVENT_CODES = frozenset({"EVENT_NOT_AUDITABLE", "PAYLOAD_INVALID"})
EVENT_MAX_TRIES = 3


class EventQueueMixin:
    def _requeue_unanswered(self) -> None:
        """Events sent but never answered go back to the front, oldest first (D-407 M3;
        the hub de-duplicates by event_id, so re-sending one it did store is harmless)."""
        entries = list(self._awaiting)
        self._awaiting.clear()
        self._requeue(entries)

    def _requeue(self, entries) -> None:
        """Put the events of these `_awaiting` entries back at the buffer front, oldest
        first, skipping any still in the buffer (an interrupted send peeks, so its event
        never left the head) — one event, one buffer slot."""
        present = {id(e) for e in self._event_buffer}
        events = []
        for kind, ev in entries:
            if kind == EnvelopeType.EVENT and ev is not None and id(ev) not in present:
                present.add(id(ev))
                events.append(ev)
        if events:
            self._event_buffer[:0] = events

    def _events_in_flight(self) -> int:
        return sum(1 for kind, _ in self._awaiting if kind == EnvelopeType.EVENT)

    async def _send(self, ws, env: Envelope) -> None:
        # Encode first: a message that cannot be encoded never enters `_awaiting`.
        await self._send_text(ws, env.type, env.model_dump_json(exclude_none=True))

    async def _send_text(self, ws, kind: EnvelopeType, text: str, ev=None) -> None:
        # Recorded before the await: the reader cannot run until we yield, so the reply
        # always finds its request at the head.
        entry = (kind, ev)
        self._awaiting.append(entry)
        try:
            await ws.send(text)
        except BaseException:
            # A failed or cancelled send is not awaited: a session that goes on must not
            # match later replies to it, and an event left at the buffer head would be
            # duplicated if its entry were requeued too.
            if self._awaiting and self._awaiting[-1] is entry:
                self._awaiting.pop()
            raise

    async def _reader_loop(self, ws) -> str:
        """The only `recv()` of a session (D-419 review): every hub message refreshes
        `last_rx`; the reply that answers our heartbeat — HEARTBEAT, or a non-fatal ERROR
        from a degraded but alive hub — wakes the heartbeat; EVENT replies are drained
        here and cannot satisfy the heartbeat deadline. A pairing ERROR ends the session."""
        while True:
            try:
                text = await ws.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if getattr(getattr(exc, 'rcvd', None), 'code', None) in (4401, 4403):
                    self.enabled = False
                logger.info("Fleet hub socket closed: %s", exc)
                return f"connection closed ({exc})"
            self.last_rx = self._clock()
            try:
                env = Envelope.model_validate_json(text)
            except ValueError:
                env = None
            if env is not None and env.type == EnvelopeType.HEARTBEAT:
                if 'junction_signal' in env.payload:
                    self.junction_signal_answer(env.payload['junction_signal'])
                # A heartbeat reply names itself; resynchronise the queue on it so a reply
                # the hub skipped cannot shift later attributions. Events it skipped are
                # unanswered: they go back to the buffer.
                answers, ev = EnvelopeType.HEARTBEAT, None
                skipped = []
                while self._awaiting:
                    entry = self._awaiting.popleft()
                    if entry[0] == EnvelopeType.HEARTBEAT:
                        break
                    skipped.append(entry)
                self._requeue(skipped)
            else:
                # ACK and ERROR do not say what they answer: the oldest outstanding request.
                answers, ev = self._awaiting.popleft() if self._awaiting else (None, None)
            if self._event_slot is not None:
                self._event_slot.set()       # an EVENT entry may have left: wake the sender
            if env is None:
                continue
            if env.type == EnvelopeType.ERROR:
                code = env.payload.get("code")
                if answers == EnvelopeType.HEARTBEAT:
                    request = self.junction_signal_request()
                    if request is not None:
                        self.junction_signal_answer(dict(request_id=request, lamp='unknown',
                                                         may_enter=False, reason='fleet_error'))
                # Hubs before PAYLOAD_INVALID answered an EVENT payload they could not
                # validate with SESSION_NOT_PAIRED, so a "fatal" code answering an EVENT is an
                # event rejection, not a pairing failure. PAIRING_INVALID is fatal either way.
                if code in SESSION_FATAL_ERRORS and (
                        answers == EnvelopeType.HEARTBEAT or code == "PAIRING_INVALID"):
                    logger.error("Fleet hub ended the session: %s", code)
                    self.junction_signal_refused = True
                    request = self.junction_signal_request()
                    if request is not None:
                        self.junction_signal_answer(dict(request_id=request, lamp='unknown',
                                                         may_enter=False, reason='link_rejected'))
                    self.enabled = False
                    self.connected = False
                    await self._abort(ws)
                    return f"hub ended the session: {code}"
                if answers == EnvelopeType.EVENT:
                    self._refuse_event(ev, code)
                else:
                    self._log_degraded(code, answers)
            elif answers == EnvelopeType.EVENT and ev is not None:
                self._tries.pop(ev.seq, None)
            # Only a HEARTBEAT reply, or an ERROR answering our heartbeat, satisfies the
            # deadline; an EVENT ACK never does, even if the hub skipped a reply.
            wakes = (env.type == EnvelopeType.HEARTBEAT
                     or (env.type == EnvelopeType.ERROR and answers == EnvelopeType.HEARTBEAT))
            if wakes and self._hb_reply is not None:
                self._hb_reply.set()

    def _refuse_event(self, ev, code) -> None:
        """An ERROR answering one of our events (D-407 review M3): EVENT_NOT_AUDITABLE
        drops it; any other code re-sends it, at most EVENT_MAX_TRIES sends in total."""
        if ev is None:
            logger.warning("Fleet hub rejected an event: %s", code)
            return
        seq, kind = ev.seq, getattr(ev, "type", "?")
        tries = self._tries.get(seq, 1)
        if code in PERMANENT_EVENT_CODES or tries >= EVENT_MAX_TRIES:
            self._tries.pop(seq, None)
            logger.warning("Fleet hub refused event seq %s (%s) after %d tries: %s; dropped",
                           seq, kind, tries, code)
            return
        self._tries[seq] = tries + 1
        logger.warning("Fleet hub could not take event seq %s (%s): %s; will re-send",
                       seq, kind, code)
        self._event_buffer.insert(0, ev)

    def _log_degraded(self, code, answers) -> None:
        """Rate-limited per (code, answered type): a heartbeat ERROR flood is logged once
        a minute. Event refusals are logged per event by `_refuse_event`."""
        key = (code, answers)
        now = self._clock()
        last = self._degraded_logged_at.get(key)
        if last is not None and now - last < DEGRADED_LOG_INTERVAL_S:
            return
        self._degraded_logged_at[key] = now
        what = getattr(answers, "value", answers)
        logger.warning("Fleet hub degraded: %s answering %s (link kept; logged at most "
                       "every %.0f s per code)", code, what, DEGRADED_LOG_INTERVAL_S)

    def _buffer_event(self, ev) -> None:
        # The bus hands every subscriber the object it keeps in its ring buffer;
        # renumber a copy so /api/v1/events and audit keep the bus seq (D-382 I4).
        self._event_seq += 1
        self._event_buffer.append(ev.model_copy(update={"seq": self._event_seq}))
        # cap buffer to prevent memory leak
        if len(self._event_buffer) > 1000:
            self._event_buffer = self._event_buffer[-1000:]

    async def _send_heartbeat(self, ws, env: Envelope) -> None:
        await self._send(ws, env)
        await self._hb_reply.wait()

    @staticmethod
    async def _abort(ws) -> None:
        """Drop the socket now. A closing handshake would wait on the silent hub."""
        transport = getattr(ws, "transport", None)
        try:
            if transport is not None:
                transport.abort()
            else:
                await asyncio.wait_for(ws.close(), timeout=0.5)
        except Exception:
            pass

    def _drop_event(self, ev) -> None:
        # The buffer may have been capped meanwhile; drop exactly this event.
        if self._event_buffer and self._event_buffer[0] is ev:
            self._event_buffer.pop(0)
        else:
            try:
                self._event_buffer.remove(ev)
            except ValueError:
                pass
