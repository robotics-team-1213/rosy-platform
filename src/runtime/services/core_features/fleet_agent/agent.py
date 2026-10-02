import asyncio
import collections
import logging
import math
import ssl
import time
import urllib.parse
from pathlib import Path

from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload, HeartbeatPayload
from .discovery import locate_fleet

logger = logging.getLogger("fleet_agent")

#: API Ref §7.6 — exponential reconnect backoff, hard cap 30 s (PRT-006).
MAX_BACKOFF_S = 30.0
#: PRT-003 heartbeat cadence.
HEARTBEAT_PERIOD_S = 1.0
#: D-419: default deadline for the hub's heartbeat reply (`fleet.heartbeat_reply_timeout_s`).
#: A missed reply closes the socket, so a half-open TCP link reads as down in seconds
#: instead of the library keepalive's ~40 s.
DEFAULT_REPLY_TIMEOUT_S = 2.0
REPLY_TIMEOUT_RANGE_S = (0.5, 10.0)
#: Jitter allowance on top of one heartbeat period plus the reply deadline.
LINK_SLACK_S = 0.5
#: D-419 review: the backoff resets only after a session survives this many answered
#: heartbeats, so a hub that welcomes and then never answers does not cause churn.
STABLE_HEARTBEATS = 3
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
#: HELLO must be answered this fast, or the session is abandoned and retried (D-407).
#: Not a SAF-003 input: the link reads as down until WELCOME whatever this is.
HELLO_TIMEOUT_S = 5.0
#: Hub codes that refuse an event for good (its content is outside the audit contract).
#: Every other ERROR to an event is treated as transient and re-sent, at most
#: EVENT_MAX_TRIES times in total, then dropped with a log line (D-407 review M3).
PERMANENT_EVENT_CODES = frozenset({"EVENT_NOT_AUDITABLE"})
EVENT_MAX_TRIES = 3
#: Unanswered EVENTs on the wire at once. The hub answers in order with one durable
#: commit per event, so a heartbeat queued behind a 1000-event backlog would miss its
#: deadline and flap the link (D-419 landing review); behind 8 it does not.
MAX_EVENTS_IN_FLIGHT = 8


def next_backoff(current: float) -> float:
    return min(current * 2.0, MAX_BACKOFF_S)


def fleet_link_configured(fleet_cfg: dict) -> bool:
    """The agent runs only with an approved pairing token and a site location."""
    fleet_cfg = fleet_cfg or {}
    discovery = fleet_cfg.get("discovery") or {}
    has_discovery = (isinstance(discovery, dict)
                     and isinstance(discovery.get("expected_hostname"), str)
                     and isinstance(discovery.get("ca_file"), str)
                     and Path(discovery["ca_file"]).is_absolute())
    return bool(fleet_cfg.get("pairing_token")) and bool(fleet_cfg.get("hub_url") or has_discovery)


def heartbeat_reply_timeout_s(fleet_cfg: dict) -> float:
    """Read and validate `fleet.heartbeat_reply_timeout_s`."""
    raw = (fleet_cfg or {}).get("heartbeat_reply_timeout_s", DEFAULT_REPLY_TIMEOUT_S)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("fleet.heartbeat_reply_timeout_s must be a number")  # noqa: TRY004
    value = float(raw)
    low, high = REPLY_TIMEOUT_RANGE_S
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"fleet.heartbeat_reply_timeout_s must be within {low}-{high} s")
    return value


class FleetAgent:
    def __init__(self, state_manager, event_bus, config: dict, identity) -> None:
        self.state = state_manager
        self.events = event_bus
        self.config = config
        self.identity = identity
        self.enabled = False
        #: `connected` is True only between the hub's WELCOME and the session ending (D-419).
        self._connected = False
        self._link_lost_at: float | None = None
        self._clock = time.monotonic
        #: time.monotonic() of the last message received from the hub, or None.
        self.last_rx: float | None = None
        fleet_cfg = (config or {}).get("fleet") or {}
        try:
            self.reply_timeout_s = heartbeat_reply_timeout_s(fleet_cfg)
        except ValueError:
            # Fail fast only on a robot that has a Fleet link; a robot without Fleet must
            # boot unaffected by Fleet settings (D-419 scope).
            if fleet_link_configured(fleet_cfg):
                raise
            logger.warning("ignoring invalid fleet.heartbeat_reply_timeout_s on a robot "
                           "without a Fleet link", exc_info=True)
            self.reply_timeout_s = DEFAULT_REPLY_TIMEOUT_S
        #: Injectable so tests run the real loop on a scaled clock.
        self.heartbeat_period_s = HEARTBEAT_PERIOD_S
        self.link_slack_s = LINK_SLACK_S
        self._task: asyncio.Task | None = None
        self._pending: tuple[str, str] | None = None
        self._ws = None
        self._event_buffer = []
        self._event_seq = 0
        self._hb_reply: asyncio.Event | None = None
        #: Set by the reader whenever an EVENT entry leaves `_awaiting` (in-flight cap).
        self._event_slot: asyncio.Event | None = None
        self._answered = 0
        #: Our messages still waiting for the hub's reply, as (type, event or None). The hub
        #: answers every message once and in order (fleet/hub/server.py), so the head is
        #: what the next reply answers.
        self._awaiting: collections.deque = collections.deque()
        self._tries: dict = {}
        self._degraded_logged_at: dict = {}
        self._stable = False
        self._end_reason = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        value = bool(value)
        if self._connected and not value:
            self._link_lost_at = self._clock()
        self._connected = value

    def linked_within(self, grace_s: float) -> bool:
        """Linked now, or lost the link at most ``grace_s`` ago (a brief reconnect, D-407)."""
        if self._connected:
            return True
        return (self._link_lost_at is not None and grace_s > 0.0
                and self._clock() - self._link_lost_at <= grace_s)

    @property
    def link_fresh_s(self) -> float:
        """Longest silence a healthy link shows: one heartbeat period + the reply deadline
        + slack. SAF-003 and the lane-stuck console link both judge freshness with it."""
        return self.heartbeat_period_s + self.reply_timeout_s + self.link_slack_s

    def recently_heard(self, now: float | None = None) -> bool:
        last_rx = self.last_rx
        if last_rx is None:
            return False
        return (self._clock() if now is None else now) - last_rx < self.link_fresh_s

    def start(self) -> None:
        fleet_cfg = self.config.get("fleet", {})
        if not fleet_link_configured(fleet_cfg):
            logger.info("Fleet agent disabled (no approved pairing token or site location)")
            return

        self.enabled = True
        self._pending = (fleet_cfg.get("hub_url") or "", fleet_cfg.get("pairing_token"))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # CoreServices.build runs before uvicorn's loop exists (no loop -> RuntimeError
            # killed CORE, D-407 sim 2026-10-02). The API startup hook calls start_on_loop().
            logger.info("Fleet agent start deferred to the API event loop")
            return
        self.start_on_loop()

    def start_on_loop(self) -> None:
        """Create the hub task on the running loop. No-op when disabled or already started."""
        if self._pending is None or self._task is not None or not self.enabled:
            return
        hub_url, pairing_token = self._pending
        self._task = asyncio.get_running_loop().create_task(self._run(hub_url, pairing_token))

    def stop(self) -> None:
        self.enabled = False
        self.connected = False
        if self._task:
            self._task.cancel()

    def hello_payload(self, pairing_token: str) -> dict:
        """PRT-002 hello 본문. 신원은 RobotIdentity 실값에서 온다 (D-170 인접)."""
        hello = HelloPayload(
            robot_id=self.identity.robot_id,
            pairing_token=pairing_token,
            device_uid=getattr(self.identity, "device_uid", "") or "",
            device_name=getattr(self.identity, "device_name", "") or "",
            model=getattr(self.identity, "model", "") or "",
            hardware_serial=getattr(self.identity, "hardware_serial", "") or "",
        )
        return hello.model_dump()

    async def _run(self, hub_url: str, pairing_token: str) -> None:
        import websockets
        from websockets.exceptions import WebSocketException

        discovery = self.config.get("fleet", {}).get("discovery") or {}
        discover = not hub_url
        ca_file = Path(discovery["ca_file"]) if discover else None

        # Keep buffering events even when disconnected to not lose them
        unsubscribe = self.events.subscribe(self._buffer_event)

        backoff = 1.0
        try:
            while self.enabled:
                stable = False
                why = None
                try:
                    current_hub = (await asyncio.to_thread(
                        locate_fleet, discovery["expected_hostname"], ca_file)
                        if discover else hub_url)
                    ws_url = urllib.parse.urljoin(current_hub, "/ws/robots").replace(
                        "http://", "ws://").replace("https://", "wss://")
                    options = ({"ssl": ssl.create_default_context(cafile=str(ca_file)),
                                "proxy": None} if discover else {})
                    self._connect(ws_url)  # for tests
                    async with websockets.connect(ws_url, **options) as ws:
                        self._ws = ws
                        why = await self._session(ws, pairing_token)
                        stable = self._stable
                        if why is None:
                            break                    # hello refused: stop for good

                except (WebSocketException, OSError) as exc:
                    logger.warning("Fleet agent disconnected: %s", exc)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("Fleet agent error: %r", exc)

                self.connected = False
                self._ws = None
                if self.enabled:
                    if stable:
                        backoff = 1.0
                    if why is not None:
                        logger.warning("Fleet agent link lost (%s); reconnecting in %.0f s",
                                       why, backoff)
                    await asyncio.sleep(backoff)
                    backoff = next_backoff(backoff)
        finally:
            self.connected = False
            unsubscribe()

    async def _session(self, ws, pairing_token: str) -> str | None:
        """HELLO, then serve. Returns why the session ended, or None when the hub refused
        HELLO (the agent then stops for good). `_stable` says whether it was stable."""
        self._stable = False
        hello = HelloPayload(**self.hello_payload(pairing_token))
        env = Envelope(type=EnvelopeType.HELLO, payload=hello.model_dump())
        await ws.send(env.model_dump_json(exclude_none=True))
        try:
            reply = Envelope.model_validate_json(
                await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S))
        except asyncio.TimeoutError:
            return f"no hello reply within {HELLO_TIMEOUT_S:g} s"
        if reply.type == EnvelopeType.ERROR:
            logger.error("Fleet hub rejected hello: %s", reply.payload.get("code"))
            self.enabled = False
            return None
        if reply.type != EnvelopeType.WELCOME:
            # D-419: the link is up only once the hub has welcomed us; an open socket
            # that never gets there is still a lost link (and does not stamp last_rx).
            return f"unexpected hello reply {reply.type.value}"
        self.last_rx = self._clock()
        logger.info("Fleet agent welcomed by hub")
        last_event_seq = reply.payload.get("last_event_seq", 0)
        self._event_buffer = [e for e in self._event_buffer if e.seq > last_event_seq]
        self._stable = await self._serve(ws)
        return self._end_reason

    async def _serve(self, ws) -> bool:
        """One welcomed session: a single reader, the heartbeat, the event sender.

        Returns True when the session survived STABLE_HEARTBEATS answered heartbeats;
        `_end_reason` names the loop that ended it and why."""
        self._hb_reply = asyncio.Event()
        self._event_slot = asyncio.Event()
        self._answered = 0
        self._awaiting.clear()
        self.connected = True
        tasks = {asyncio.create_task(self._reader_loop(ws)): "receive",
                 asyncio.create_task(self._heartbeat_loop(ws)): "heartbeat",
                 asyncio.create_task(self._event_loop(ws)): "event"}
        done: set = set()
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.connected = False
            self._requeue_unanswered()
        ended = next(iter(done)) if done else None
        if ended is None or ended.cancelled():
            self._end_reason = f"{tasks.get(ended, 'session')} loop ended: cancelled"
        else:
            error = ended.exception()
            self._end_reason = (f"{tasks[ended]} loop ended: "
                                f"{ended.result() if error is None else error}")
        return self._answered >= STABLE_HEARTBEATS

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
                logger.info("Fleet hub socket closed: %s", exc)
                return f"connection closed ({exc})"
            self.last_rx = self._clock()
            try:
                env = Envelope.model_validate_json(text)
            except ValueError:
                env = None
            if env is not None and env.type == EnvelopeType.HEARTBEAT:
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
                # The hub answers an EVENT payload it cannot validate with SESSION_NOT_PAIRED
                # (hub.py `_event`), so a "fatal" code answering an EVENT is an event
                # rejection, not a pairing failure. PAIRING_INVALID is fatal either way.
                if code in SESSION_FATAL_ERRORS and (
                        answers == EnvelopeType.HEARTBEAT or code == "PAIRING_INVALID"):
                    logger.error("Fleet hub ended the session: %s", code)
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
        now = time.monotonic()
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

    async def _heartbeat_loop(self, ws) -> str:
        import websockets
        while self.enabled:
            try:
                snap = self.state.snapshot()
                hb = HeartbeatPayload(state_snapshot=snap)
                env = Envelope(type=EnvelopeType.HEARTBEAT, payload=hb.model_dump(mode="json"))
                # One heartbeat outstanding at a time: clear before sending so only the
                # reply to this one can wake us.
                self._hb_reply.clear()
                # One deadline over send and reply: a send held in drain also aborts.
                await asyncio.wait_for(self._send_heartbeat(ws, env), timeout=self.reply_timeout_s)
            except asyncio.TimeoutError:
                logger.warning("Fleet hub did not answer a heartbeat within %.1f s; aborting",
                               self.reply_timeout_s)
                self.connected = False
                await self._abort(ws)
                return f"no heartbeat reply within {self.reply_timeout_s:g} s"
            except websockets.exceptions.WebSocketException as exc:
                return f"send failed ({exc})"
            except Exception as exc:
                logger.error("heartbeat loop error: %s", exc)
                return f"error ({exc})"
            self._answered += 1
            await asyncio.sleep(self.heartbeat_period_s)
        return "agent disabled"

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

    async def _event_loop(self, ws) -> str:
        """Peek, encode, send, then pop.

        An event that cannot be encoded (non-JSON data the bus did not check) is logged
        and dropped — kept at the head it would kill every session (D-419 round 4). One
        whose send fails on the transport or is cancelled stays for the next session; any
        other send error drops it and the loop goes on. A sent event waits in `_awaiting`
        for the hub's answer: an ERROR may send it again (`_refuse_event`), and one still
        unanswered when the session ends goes back to the buffer (D-407 M3). At most
        MAX_EVENTS_IN_FLIGHT events wait for an answer at once, so a heartbeat never
        queues behind a long backlog at the hub."""
        import websockets
        if self._event_slot is None:
            self._event_slot = asyncio.Event()
        while self.enabled:
            if not self._event_buffer:
                await asyncio.sleep(0.1)
                continue
            if self._events_in_flight() >= MAX_EVENTS_IN_FLIGHT:
                self._event_slot.clear()
                await self._event_slot.wait()
                continue
            ev = self._event_buffer[0]
            try:
                text = Envelope(type=EnvelopeType.EVENT,
                                payload=ev.model_dump(mode="json")).model_dump_json(exclude_none=True)
            except Exception as exc:
                logger.error("dropping event seq %s: cannot encode it (%r)",
                             getattr(ev, "seq", "?"), exc)
                self._drop_event(ev)
                continue
            try:
                await self._send_text(ws, EnvelopeType.EVENT, text, ev)
            except (websockets.exceptions.WebSocketException, OSError) as exc:
                return f"send failed ({exc})"   # transport gone: keep it for the next session
            except Exception as exc:
                logger.error("dropping event seq %s: send failed (%r)",
                             getattr(ev, "seq", "?"), exc)
                self._drop_event(ev)
                continue
            self._drop_event(ev)
        return "agent disabled"

    def _connect(self, url: str) -> None:
        pass
