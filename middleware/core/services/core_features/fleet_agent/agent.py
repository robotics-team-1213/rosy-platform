import asyncio
import collections
import logging
import math
import ssl
import time
import urllib.parse
from pathlib import Path

from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload
from core_common.link_retry import retry_delay
from .discovery import locate_fleet, approved_profile, DiscoveryConflict, DiscoveryUnavailable
from .event_queue import (
    DEGRADED_LOG_INTERVAL_S,
    EVENT_MAX_TRIES,
    PERMANENT_EVENT_CODES,
    SESSION_FATAL_ERRORS,
    EventQueueMixin,
)
from .heartbeat import HeartbeatLoop

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
#: HELLO must be answered this fast, or the session is abandoned and retried (D-407).
#: Not a SAF-003 input: the link reads as down until WELCOME whatever this is.
HELLO_TIMEOUT_S = 5.0
#: Unanswered EVENTs on the wire at once. The hub answers in order with one durable
#: commit per event, so a heartbeat queued behind a 1000-event backlog would miss its
#: deadline and flap the link (D-419 landing review); behind 8 it does not.
MAX_EVENTS_IN_FLIGHT = 8


def next_backoff(current: float) -> float:
    return min(current * 2.0, MAX_BACKOFF_S)


def _discovery_profile(fleet_cfg: dict) -> dict | None:
    """A declared trust profile must never fall back to a legacy URL."""
    return approved_profile(fleet_cfg)


def fleet_link_configured(fleet_cfg: dict) -> bool:
    """The agent runs only with an approved pairing token and a site location."""
    fleet_cfg = fleet_cfg or {}
    try:
        discovery = _discovery_profile(fleet_cfg)
    except ValueError:
        return False
    return bool(fleet_cfg.get("pairing_token")) and bool(discovery or fleet_cfg.get("hub_url"))


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


class FleetAgent(HeartbeatLoop, EventQueueMixin):
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
        #: D-555: unarmed from a relink (relinked_at) to WELCOME or grace (SAF-003); boot defaults.
        self.armed, self.relinked_at, self.config_fallback = True, None, None
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
            self.config_fallback = "fleet.heartbeat_reply_timeout_s is invalid"
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
        self.junction_signal_request = lambda: None
        self.junction_signal_answer = lambda answer: False
        self.junction_signal_refused = False

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
        # D-452: approved identity/CA pins win over a stale transport URL.
        hub_url = "" if _discovery_profile(fleet_cfg) else fleet_cfg.get("hub_url") or ""
        self._pending = (hub_url, fleet_cfg.get("pairing_token"))
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

    def relink(self, fleet_cfg: dict) -> None:
        """D-555: swap `config["fleet"]` (SAF-003 reads it) and restart only this task."""
        self.stop()
        self.junction_signal_refused = False
        self._task = self._pending = None
        self.armed, self.relinked_at = False, self._clock()
        self.config["fleet"] = fleet_cfg
        self.start()

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

        try:
            discovery = _discovery_profile(self.config.get("fleet", {}) or {})
        except ValueError as exc:
            logger.error("Fleet link configuration rejected: %s", exc)
            self.enabled = False
            return
        discover = discovery is not None
        if not discover and not hub_url:
            self.enabled = False
            return
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
                        locate_fleet, discovery["expected_hostname"], ca_file,
                        **({'approved_directory_url': discovery['approved_directory_url']}
                           if 'approved_directory_url' in discovery else {}))
                        if discover else hub_url)
                    ws_url = urllib.parse.urljoin(current_hub, "/ws/robots").replace(
                        "http://", "ws://").replace("https://", "wss://")
                    options = ({"ssl": ssl.create_default_context(cafile=str(ca_file)),
                                "proxy": None} if discover else {})
                    if discover and getattr(current_hub, 'address', None):
                        options.update(host=current_hub.address, port=current_hub.port,
                                       server_hostname=discovery['expected_hostname'])
                    self._connect(ws_url)  # for tests
                    async with websockets.connect(ws_url, **options) as ws:
                        self._ws = ws
                        why = await self._session(ws, pairing_token)
                        stable = self._stable
                        if why is None:
                            break                    # hello refused: stop for good

                except (ssl.SSLCertVerificationError, DiscoveryConflict) as exc:
                    logger.error('Fleet link requires operator: %s', exc)
                    self.enabled = False
                    break
                except DiscoveryUnavailable as exc:
                    logger.warning('Fleet peer temporarily absent: %s', exc)
                except ValueError as exc:
                    logger.error('Fleet link configuration rejected: %s', exc)
                    self.enabled = False
                    break
                except (WebSocketException, OSError) as exc:
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    code = getattr(getattr(exc, 'rcvd', None), 'code', None)
                    if status in (401, 403) or code in (4401, 4403):
                        logger.error('Fleet authentication rejected; operator action required')
                        self.enabled = False
                        break
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
                    delay = retry_delay(backoff, maximum_s=MAX_BACKOFF_S)
                    if why is not None:
                        logger.warning("Fleet agent link lost (%s); reconnecting in %.0f s",
                                       why, delay)
                    await asyncio.sleep(delay)
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
            self.junction_signal_refused = True
            self.enabled = False
            return None
        if reply.type != EnvelopeType.WELCOME:
            # D-419: the link is up only once the hub has welcomed us; an open socket
            # that never gets there is still a lost link (and does not stamp last_rx).
            return f"unexpected hello reply {reply.type.value}"
        self.last_rx = self._clock()
        self.armed = True
        logger.info("Fleet agent welcomed by hub")
        # A robot-wide sequence maximum cannot acknowledge events from this producer.
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
        if len(self._event_buffer) > MAX_EVENTS_IN_FLIGHT:   # network load: robots reconnecting together
            await asyncio.sleep(retry_delay(0.5, maximum_s=0.5))   # replay a backlog 0.25-0.5 s apart
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
