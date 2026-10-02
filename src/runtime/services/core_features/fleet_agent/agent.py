import asyncio
import logging
import ssl
import time
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Optional

from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload, HeartbeatPayload
from .discovery import locate_fleet

logger = logging.getLogger("fleet_agent")

#: API Ref §7.6 — exponential reconnect backoff, hard cap 30 s (PRT-006).
MAX_BACKOFF_S = 30.0
#: HELLO must be answered this fast, or the session is abandoned and retried.
HELLO_TIMEOUT_S = 5.0
#: Hub codes that refuse an event for good (its content is outside the audit contract).
#: Every other ERROR to an event is treated as transient and re-sent, at most
#: EVENT_MAX_TRIES times in total, then dropped with a log line.
PERMANENT_EVENT_CODES = frozenset({"EVENT_NOT_AUDITABLE"})
EVENT_MAX_TRIES = 3


def next_backoff(current: float) -> float:
    return min(current * 2.0, MAX_BACKOFF_S)


class FleetAgent:
    def __init__(self, state_manager, event_bus, config: dict, identity) -> None:
        self.state = state_manager
        self.events = event_bus
        self.config = config
        self.identity = identity
        self.enabled = False
        self._connected = False
        self._link_lost_at: Optional[float] = None
        self._clock = time.monotonic
        self._task: Optional[asyncio.Task] = None
        self._pending: Optional[tuple[str, str]] = None
        self._ws = None
        self._event_buffer = []
        self._event_seq = 0
        # Sent envelopes awaiting their in-order hub reply: ("heartbeat", None) or ("event", ev).
        self._inflight: deque = deque()
        self._tries: dict[int, int] = {}
        self._send_lock: Optional[asyncio.Lock] = None
        self._welcomed = False

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

    def start(self) -> None:
        fleet_cfg = self.config.get("fleet", {})
        hub_url = fleet_cfg.get("hub_url")
        pairing_token = fleet_cfg.get("pairing_token")
        discovery = fleet_cfg.get("discovery") or {}
        has_discovery = (isinstance(discovery, dict)
                         and isinstance(discovery.get("expected_hostname"), str)
                         and isinstance(discovery.get("ca_file"), str)
                         and Path(discovery["ca_file"]).is_absolute())

        if not pairing_token or not (hub_url or has_discovery):
            logger.info("Fleet agent disabled (no approved pairing token or site location)")
            return

        self.enabled = True
        self._pending = (hub_url or "", pairing_token)
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
                        self._welcomed = False
                        try:
                            why = await self._session(ws, pairing_token)
                        finally:
                            self.connected = False   # linked only between WELCOME and exit
                        if self._welcomed:
                            backoff = 1.0            # reset only after a real WELCOME
                        if why is None:
                            break                    # hello refused: stop for good
                        if self.enabled:
                            logger.warning("Fleet agent link lost (%s); reconnecting in %.0f s",
                                           why, backoff)

                except (WebSocketException, OSError) as exc:
                    self.connected = False
                    logger.warning("Fleet agent disconnected: %s", exc)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    self.connected = False
                    logger.error("Fleet agent error: %s", exc)

                self.connected = False
                self._ws = None
                if self.enabled:
                    await asyncio.sleep(backoff)
                    backoff = next_backoff(backoff)
        finally:
            unsubscribe()

    async def _session(self, ws, pairing_token: str) -> Optional[str]:
        """HELLO, then send heartbeats and events while ONE reader drains every reply.

        The hub answers each heartbeat and each event (EVENT accepted or ERROR). The old
        loop read one reply per heartbeat, so event replies piled up unread; the client's
        receive queue filled, it stopped reading the socket, keepalive pongs went unread and
        the link timed out mid-stuck (D-407 Gazebo re-run 2026-10-02: `no_console` after
        ~10 s, hub "websocket.send after websocket.close"). Returns why the session ended,
        or None when the hub refused HELLO.
        """
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
            return f"unexpected hello reply {reply.type.value}"
        logger.info("Fleet agent welcomed by hub")
        last_event_seq = reply.payload.get("last_event_seq", 0)
        self._welcomed = True
        self.connected = True
        self._event_buffer = [e for e in self._event_buffer if e.seq > last_event_seq]
        self._inflight.clear()
        self._send_lock = asyncio.Lock()
        tasks = {
            asyncio.create_task(self._receive_loop(ws)): "receive",
            asyncio.create_task(self._heartbeat_loop(ws)): "heartbeat",
            asyncio.create_task(self._event_loop(ws)): "event",
        }
        done: set = set()
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Let every loop finish its own cleanup (an event cancelled mid-send re-buffers).
            await asyncio.gather(*tasks, return_exceptions=True)
            self._requeue_unanswered()
        ended = next(iter(done)) if done else None
        if ended is None or ended.cancelled():
            return f"{tasks.get(ended, 'session')} loop ended: cancelled"
        error = ended.exception()
        return f"{tasks[ended]} loop ended: {ended.result() if error is None else error}"

    def _requeue_unanswered(self) -> None:
        """Events sent but never answered go back to the front, oldest first (the hub
        de-duplicates by event_id, so a re-send of one it did store is harmless)."""
        unanswered = [ev for kind, ev in self._inflight if kind == "event"]
        self._inflight.clear()
        if unanswered:
            self._event_buffer[:0] = unanswered

    def _settle(self, reply: Envelope) -> None:
        """Match one hub reply to the oldest sent envelope (the hub answers in order)."""
        if not self._inflight:
            logger.debug("Fleet hub reply with nothing in flight: %s", reply.type.value)
            return
        kind, ev = self._inflight.popleft()
        if reply.type != EnvelopeType.ERROR:
            if ev is not None:
                self._tries.pop(ev.seq, None)
            return
        code = reply.payload.get("code")
        if kind != "event":
            logger.warning("Fleet hub refused a %s: %s", kind, code)
            return
        tries = self._tries.get(ev.seq, 1)
        if code in PERMANENT_EVENT_CODES or tries >= EVENT_MAX_TRIES:
            self._tries.pop(ev.seq, None)
            logger.warning("Fleet hub refused event seq %s (%s) after %d tries: %s; dropped",
                           ev.seq, ev.type, tries, code)
            return
        self._tries[ev.seq] = tries + 1
        logger.warning("Fleet hub could not take event seq %s (%s): %s; will re-send",
                       ev.seq, ev.type, code)
        self._event_buffer.insert(0, ev)

    async def _send(self, ws, kind: str, env: Envelope, ev=None) -> None:
        """Send one envelope and remember it, in wire order, for its reply."""
        async with self._send_lock:
            self._inflight.append((kind, ev))
            try:
                await ws.send(env.model_dump_json(exclude_none=True))
            except BaseException:
                self._inflight.pop()             # never reached the wire (or unknown): retry
                raise

    async def _receive_loop(self, ws) -> str:
        """Drain every hub reply. An ERROR reply refuses one envelope; the link stays."""
        import websockets
        try:
            async for text in ws:
                try:
                    reply = Envelope.model_validate_json(text)
                except ValueError:
                    logger.warning("Fleet hub sent an unreadable reply; ignored")
                    continue
                self._settle(reply)
                if reply.type == EnvelopeType.ERROR and reply.payload.get("code") == "PAIRING_INVALID":
                    return "hub refused pairing"
        except websockets.exceptions.ConnectionClosed as exc:
            return f"connection closed ({exc})"
        return "connection closed"

    def _buffer_event(self, ev) -> None:
        # The bus hands every subscriber the object it keeps in its ring buffer;
        # renumber a copy so /api/v1/events and audit keep the bus seq (D-382 I4).
        self._event_seq += 1
        self._event_buffer.append(ev.model_copy(update={"seq": self._event_seq}))
        # cap buffer to prevent memory leak
        if len(self._event_buffer) > 1000:
            self._event_buffer = self._event_buffer[-1000:]

    async def _heartbeat_loop(self, ws) -> None:
        import websockets
        while self.enabled:
            try:
                snap = self.state.snapshot()
                hb = HeartbeatPayload(state_snapshot=snap)
                env = Envelope(type=EnvelopeType.HEARTBEAT, payload=hb.model_dump(mode="json"))
                await self._send(ws, "heartbeat", env)
                # The reply is drained by _receive_loop; reading it here desynced the link.
            except websockets.exceptions.WebSocketException as exc:
                return f"send failed ({exc})"
            except Exception as exc:
                logger.error("heartbeat loop error: %s", exc)
                return f"error ({exc})"
            await asyncio.sleep(1.0)
        return "agent disabled"

    async def _event_loop(self, ws) -> None:
        import websockets
        while self.enabled:
            ev = None
            try:
                if self._event_buffer:
                    ev = self._event_buffer.pop(0)
                    self._tries.setdefault(ev.seq, 1)
                    env = Envelope(type=EnvelopeType.EVENT, payload=ev.model_dump(mode="json"))
                    await self._send(ws, "event", env, ev)
                else:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                if ev is not None and not any(sent is ev for _, sent in self._inflight):
                    self._event_buffer.insert(0, ev)   # cancelled mid-send: keep it
                raise
            except websockets.exceptions.WebSocketException as exc:
                # Re-insert the event at the front if we failed to send
                self._event_buffer.insert(0, ev)
                return f"send failed ({exc})"
            except Exception as exc:
                logger.error("event loop error: %s", exc)
                return f"error ({exc})"
        return "agent disabled"

    def _connect(self, url: str) -> None:
        pass
