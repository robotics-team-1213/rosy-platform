"""Heartbeat send/reply loop on the existing FleetAgent session."""
import asyncio
import logging

from core_common.protocol.schemas import Envelope, EnvelopeType, HeartbeatPayload

logger = logging.getLogger("fleet_agent")


class HeartbeatLoop:
    async def _heartbeat_loop(self, ws) -> str:
        import websockets
        while self.enabled:
            try:
                snap = self.state.snapshot()
                hb = HeartbeatPayload(state_snapshot=snap,
                                      junction_signal_request=self.junction_signal_request())
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
