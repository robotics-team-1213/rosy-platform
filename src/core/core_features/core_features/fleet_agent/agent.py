import asyncio
import json
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload, HeartbeatPayload, EventMessage

logger = logging.getLogger("fleet_agent")

#: API Ref §7.6 — exponential reconnect backoff, hard cap 30 s (PRT-006).
MAX_BACKOFF_S = 30.0


def next_backoff(current: float) -> float:
    return min(current * 2.0, MAX_BACKOFF_S)


class FleetAgent:
    def __init__(self, state_manager, event_bus, config: dict, identity) -> None:
        self.state = state_manager
        self.events = event_bus
        self.config = config
        self.identity = identity
        self.enabled = False
        self.connected = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None
        self._event_buffer = []
        self._event_seq = 0

    def start(self) -> None:
        fleet_cfg = self.config.get("fleet", {})
        hub_url = fleet_cfg.get("hub_url")
        pairing_token = fleet_cfg.get("pairing_token")
        
        if not hub_url or not pairing_token:
            logger.info("Fleet agent disabled (no hub_url or token)")
            return
            
        self.enabled = True
        self._task = asyncio.create_task(self._run(hub_url, pairing_token))

    def stop(self) -> None:
        self.enabled = False
        self.connected = False
        if self._task:
            self._task.cancel()

    async def _run(self, hub_url: str, pairing_token: str) -> None:
        import websockets
        from websockets.exceptions import WebSocketException
        
        ws_url = urllib.parse.urljoin(hub_url, "/ws/robots").replace("http://", "ws://").replace("https://", "wss://")
        
        # Keep buffering events even when disconnected to not lose them
        def on_event(ev):
            self._event_seq += 1
            ev.seq = self._event_seq
            self._event_buffer.append(ev)
            # cap buffer to prevent memory leak
            if len(self._event_buffer) > 1000:
                self._event_buffer = self._event_buffer[-1000:]
                
        self.events.subscribe(on_event)
        
        backoff = 1.0
        try:
            while self.enabled:
                try:
                    self._connect(ws_url) # for tests
                    async with websockets.connect(ws_url) as ws:
                        self._ws = ws
                        self.connected = True
                        backoff = 1.0
                        
                        hello = HelloPayload(
                            robot_id=self.identity.robot_id,
                            pairing_token=pairing_token,
                            device_uid=self.identity.device_uid if hasattr(self.identity, 'device_uid') else "",
                            device_name=self.identity.device_name if hasattr(self.identity, 'device_name') else "",
                            model=self.identity.model if hasattr(self.identity, 'model') else "",
                            hardware_serial=self.identity.hardware_serial if hasattr(self.identity, 'hardware_serial') else "",
                        )
                        env = Envelope(type=EnvelopeType.HELLO, payload=hello.model_dump())
                        await ws.send(env.model_dump_json(exclude_none=True))
                        
                        reply_text = await ws.recv()
                        reply = Envelope.model_validate_json(reply_text)
                        if reply.type == EnvelopeType.ERROR:
                            logger.error("Fleet hub rejected hello: %s", reply.payload.get("code"))
                            self.enabled = False
                            break
                            
                        last_event_seq = 0
                        if reply.type == EnvelopeType.WELCOME:
                            logger.info("Fleet agent welcomed by hub")
                            last_event_seq = reply.payload.get("last_event_seq", 0)
                        
                        # Prune buffer up to last_event_seq
                        self._event_buffer = [e for e in self._event_buffer if e.seq > last_event_seq]
                        
                        hb_task = asyncio.create_task(self._heartbeat_loop(ws))
                        ev_task = asyncio.create_task(self._event_loop(ws))
                        
                        done, pending = await asyncio.wait(
                            [hb_task, ev_task],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in pending:
                            task.cancel()
                            
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
            self.events.unsubscribe(on_event)

    async def _heartbeat_loop(self, ws) -> None:
        import websockets
        while self.enabled:
            try:
                snap = self.state.snapshot()
                hb = HeartbeatPayload(state_snapshot=snap)
                env = Envelope(type=EnvelopeType.HEARTBEAT, payload=hb.model_dump(mode="json"))
                await ws.send(env.model_dump_json(exclude_none=True))
                await ws.recv()
            except websockets.exceptions.WebSocketException:
                break
            except Exception as exc:
                logger.error("heartbeat loop error: %s", exc)
                break
            await asyncio.sleep(1.0)

    async def _event_loop(self, ws) -> None:
        import websockets
        while self.enabled:
            try:
                if self._event_buffer:
                    ev = self._event_buffer.pop(0)
                    env = Envelope(type=EnvelopeType.EVENT, payload=ev.model_dump(mode="json"))
                    await ws.send(env.model_dump_json(exclude_none=True))
                else:
                    await asyncio.sleep(0.1)
            except websockets.exceptions.WebSocketException:
                # Re-insert the event at the front if we failed to send
                self._event_buffer.insert(0, ev)
                break
            except Exception as exc:
                logger.error("event loop error: %s", exc)
                break

    def _connect(self, url: str) -> None:
        pass
