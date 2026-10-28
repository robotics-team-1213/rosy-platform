"""Discord transport only; the injected consumer owns durable named reception."""
import asyncio
import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from core_common.link_retry import ReconnectBackoff, start_offset
from .intake import project_message

LOG = logging.getLogger(__name__)


class GatewayStop(Exception):
    """Permanent connection refusal or an unresolved receipt delivery gap."""


@dataclass
class DiscordGateway(ReconnectBackoff):   # D-432 reconnect backoff (network load)
    token: str = field(repr=False)
    guild_id: str
    channel_id: str
    bot_id: str
    consume: object = field(repr=False)
    withdraw: object = field(default=None,repr=False)
    session_id: str | None = None
    sequence: int | None = None
    awaiting_ack: bool = False
    pending: bool = False
    url: str = "wss://gateway.discord.gg"

    async def authenticate(self, socket):
        if self.session_id is not None:
            payload = {"op": 6, "d": {"token": self.token, "session_id": self.session_id, "seq": self.sequence}}
        else:
            payload = {"op": 2, "d": {"token": self.token, "intents": 513,
                       "properties": {"os": "linux", "browser": "rosy-fleet", "device": "rosy-fleet"}}}
        await socket.send(json.dumps(payload))

    async def heartbeat(self, socket):
        if self.awaiting_ack:
            await socket.close(code=4000)
            return False
        self.awaiting_ack = True
        await socket.send(json.dumps({"op": 1, "d": self.sequence}))
        return True

    async def dispatch(self, packet):
        event, data = packet.get("t"), packet.get("d")
        if event == "READY":
            if data.get("user", {}).get("id") != self.bot_id or data.get("user", {}).get("bot") is not True:
                raise GatewayStop("Discord Bot identity mismatch")
            resume = data.get("resume_gateway_url", self.url)
            parsed = urlsplit(resume)
            if (parsed.scheme != "wss"
                    or not re.fullmatch(r"gateway(?:-[a-z0-9-]+)?\.discord\.gg", parsed.hostname or "")
                    or parsed.port is not None or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
                raise GatewayStop("Discord resume endpoint refused")
            self.url, self.session_id = resume.rstrip("/"), data["session_id"]
            LOG.info("Discord Gateway READY")
        elif event in {'MESSAGE_UPDATE','MESSAGE_DELETE','MESSAGE_DELETE_BULK'}:
            if self.session_id is None:
                raise GatewayStop('Discord withdrawal before verified READY')
            if (type(data) is dict and data.get('guild_id')==self.guild_id
                    and data.get('channel_id')==self.channel_id and self.withdraw is not None):
                ids=data.get('ids',[]) if event=='MESSAGE_DELETE_BULK' else [data.get('id')]
                if type(ids) is not list or len(ids)>100:raise GatewayStop('Discord withdrawal scope refused')
                for message in ids:
                    if type(message) is str and re.fullmatch(r'[0-9]{17,20}',message):
                        self.pending=True
                        await self.withdraw(self.guild_id,self.channel_id,message,event)
                        self.pending=False
        elif event == "MESSAGE_CREATE":
            if self.session_id is None:
                raise GatewayStop("Discord message before verified READY")
            envelope = project_message(data, guild_id=self.guild_id, channel_id=self.channel_id, bot_id=self.bot_id)
            if envelope is not None:
                self.pending = True
                await self.consume(envelope)
                self.pending = False
        if packet.get("s") is not None:
            self.sequence = packet["s"]

    async def pulse(self, socket, interval):
        await asyncio.sleep(start_offset(interval))
        while await self.heartbeat(socket):
            await asyncio.sleep(interval)

    async def session(self):
        async with connect(self.url + "/?v=10&encoding=json", max_size=1024 * 1024,
                           open_timeout=15, close_timeout=5, ping_interval=None) as socket:
            hello = json.loads(await asyncio.wait_for(socket.recv(), 15))
            if hello.get("op") == 7:
                await socket.close(code=4000)
                return
            interval = hello.get("d", {}).get("heartbeat_interval")
            if hello.get("op") != 10 or type(interval) not in (int, float) or not 1000 <= interval <= 120000:
                raise GatewayStop("Discord HELLO refused")
            self.awaiting_ack = False
            pulse = asyncio.create_task(self.pulse(socket, interval / 1000))
            try:
                await self.authenticate(socket)
                async for raw in socket:
                    packet = json.loads(raw)
                    opcode = packet.get("op")
                    if opcode == 0:
                        await self.dispatch(packet)
                    elif opcode == 11:
                        self.awaiting_ack = False
                    elif opcode == 1:
                        await socket.send(json.dumps({"op": 1, "d": self.sequence}))
                        self.awaiting_ack = True
                    elif opcode == 7:
                        await socket.close(code=4000)
                        return
                    elif opcode == 9:
                        if packet.get("d") is not True:
                            self.forget_session()
                        await socket.close(code=4000)
                        return
            except (OSError, TimeoutError):
                # Normal closure invalidates Discord sessions; preserve replay on journal failure.
                await socket.close(code=4000)
                raise
            finally:
                pulse.cancel()
                with suppress(asyncio.CancelledError, ConnectionClosed):
                    await pulse

    def forget_session(self):
        if self.pending:
            raise GatewayStop("Discord receipt unresolved; manual readback required")
        # shortcut: no historical backfill across process/session loss; operator must resubmit after readback.
        self.session_id, self.sequence, self.url = None, None, "wss://gateway.discord.gg"

    async def run(self):
        while True:
            try:
                await self.session()
            except GatewayStop:
                LOG.error("Discord Gateway stopped; configuration or receipt readback required")
                return
            except InvalidStatus as error:
                if error.response.status_code not in (500, 502, 503, 504):
                    LOG.error("Discord Gateway handshake refused")
                    return
                LOG.warning("Discord Gateway retrying temporary handshake failure")
            except ConnectionClosed as error:
                code = getattr(error.rcvd, "code", None)
                if code in (4004, 4010, 4011, 4012, 4013, 4014):
                    LOG.error("Discord Gateway refused credentials or intents")
                    return
                if code in (4007, 4009):
                    try:
                        self.forget_session()
                    except GatewayStop:
                        LOG.error("Discord Gateway stopped with unresolved receipt")
                        return
            except (OSError, TimeoutError, ValueError):
                LOG.warning("Discord Gateway reconnecting after transport or journal failure")
            except Exception:
                LOG.error("Discord Gateway stopped after invalid transport state")
                return
            await asyncio.sleep(self.reconnect_delay())
