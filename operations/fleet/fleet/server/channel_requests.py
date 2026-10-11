"""Fleet-owned named reception journal; no work creation or device authority."""
import hashlib
import hmac
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core_common.protocol.channel_requests import DiscordRequestEnvelope, ChannelRequestReceipt, ChannelRequestList
from .sqlite_policy import configure_connection


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    guild_id: str = Field(pattern=r"^[0-9]{17,20}$")
    channel_id: str = Field(pattern=r"^[0-9]{17,20}$")
    bot_id: str = Field(pattern=r"^[0-9]{17,20}$")
    transport_key: str = Field(min_length=32, max_length=128, repr=False, exclude=True)
    users: dict[str, str] = Field(min_length=1, max_length=100)

    @classmethod
    def load(cls, path):
        try:
            return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, yaml.YAMLError):
            raise ValueError("invalid Discord intake configuration") from None


class ChannelRequests:
    def __init__(self, path, config, accounts, *, max_rows=1000):
        if type(max_rows) is not int or not 1 <= max_rows <= 1000:
            raise ValueError("invalid channel journal capacity")
        self.path, self.config, self.accounts, self.max_rows = Path(path), config, accounts, max_rows
        if any(not re.fullmatch(r"[0-9]{17,20}", user) or accounts.get(principal) != "operator"
               for user, principal in config.users.items()):
            raise ValueError("Discord users require currently registered operators")
        with closing(self._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_requests (
                guild_id TEXT, channel_id TEXT, message_id TEXT, digest TEXT NOT NULL,
                principal_id TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY(guild_id, channel_id, message_id))''')

    def _connect(self):
        return configure_connection(sqlite3.connect(self.path, timeout=5))

    def operator(self, principal):
        if (self.accounts.get(principal) != "operator" or principal == "site-console"
                or principal.startswith("development-")):
            raise HTTPException(403, detail="CHANNEL_OPERATOR_REQUIRED")

    def receive(self, envelope):
        cfg = self.config
        if (envelope.guild_id != cfg.guild_id or envelope.channel_id != cfg.channel_id
                or envelope.author_bot or envelope.webhook_id is not None or cfg.bot_id not in envelope.mentions
                or not envelope.content.strip() or "\x00" in envelope.content):
            raise HTTPException(403, detail="CHANNEL_SCOPE_DENIED")
        principal = cfg.users.get(envelope.author_id)
        self.operator(principal)
        digest = hashlib.sha256(envelope.model_dump_json().encode()).hexdigest()
        scope = (envelope.guild_id, envelope.channel_id, envelope.message_id)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT digest, receipt FROM fleet_channel_requests WHERE "
                               "guild_id=? AND channel_id=? AND message_id=?", scope).fetchone()
            if old:
                if old[0] != digest:
                    raise HTTPException(409, detail="CHANNEL_MESSAGE_CHANGED")
                receipt = json.loads(old[1])
                if receipt["principal_id"] != principal:
                    raise HTTPException(403, detail="CHANNEL_OWNER_CHANGED")
                return receipt
            if conn.execute("SELECT COUNT(*) FROM fleet_channel_requests").fetchone()[0] >= self.max_rows:
                raise HTTPException(503, detail="CHANNEL_JOURNAL_FULL")
            receipt = ChannelRequestReceipt(
                request_id=hashlib.sha256("/".join(scope).encode()).hexdigest()[:24], principal_id=principal,
                guild_id=envelope.guild_id, channel_id=envelope.channel_id, message_id=envelope.message_id,
                author_id=envelope.author_id, content=envelope.content,
                content_hash=hashlib.sha256(envelope.content.encode()).hexdigest(),
                received_at=datetime.now(timezone.utc).isoformat()).model_dump()
            conn.execute("INSERT INTO fleet_channel_requests VALUES (?, ?, ?, ?, ?, ?)",
                         (*scope, digest, principal, json.dumps(receipt, ensure_ascii=False)))
        return receipt

    def read(self, principal):
        self.operator(principal)
        with closing(self._connect()) as conn:
            return [json.loads(row[0]) for row in conn.execute(
                "SELECT receipt FROM fleet_channel_requests WHERE principal_id=? ORDER BY rowid DESC LIMIT 50",
                (principal,))]


def install_channel_routes(app, journal, *, require_operator, read_guard, clock=time.time):
    @app.post("/api/fleet/channel-requests/discord", response_model=ChannelRequestReceipt, tags=["fleet-work"])
    async def discord_request(request: Request):
        # Bound the stream before parsing; Content-Length is not trusted.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, detail="CHANNEL_BODY_TOO_LARGE")
        timestamp = request.headers.get("X-ROSY-Timestamp", "")
        signature = request.headers.get("X-ROSY-Signature", "")
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
            raise HTTPException(401, detail="CHANNEL_TRANSPORT_REQUIRED")
        expected = hmac.new(journal.config.transport_key.encode(), timestamp.encode() + b"." + bytes(body),
                            hashlib.sha256).hexdigest()
        if (not re.fullmatch(r"[0-9a-f]{64}", signature) or abs(clock() - int(timestamp)) > 60
                or not hmac.compare_digest(signature, expected)):
            raise HTTPException(401, detail="CHANNEL_TRANSPORT_REQUIRED")
        try:
            envelope = DiscordRequestEnvelope.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, detail="CHANNEL_ENVELOPE_INVALID") from None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(journal.receive, envelope)

    @app.get("/api/fleet/channel-requests", dependencies=read_guard,
             response_model=ChannelRequestList, tags=["fleet-work"])
    def requests(principal=Depends(require_operator)):
        return {"rows": journal.read(principal.principal_id)}
