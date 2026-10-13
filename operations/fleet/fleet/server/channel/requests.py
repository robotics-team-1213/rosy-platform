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
from ..sqlite_policy import configure_connection


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    guild_id: str = Field(pattern=r"^[0-9]{17,20}$")
    channel_id: str = Field(pattern=r"^[0-9]{17,20}$")
    bot_id: str = Field(pattern=r"^[0-9]{17,20}$")
    transport_key: str = Field(min_length=32, max_length=128, repr=False, exclude=True)
    users: dict[str, str] = Field(min_length=1, max_length=100)
    bot_token_file: str | None = Field(default=None, min_length=1, max_length=4096)
    replies_enabled: bool = False
    hourly_health_enabled: bool = False

    @classmethod
    def load(cls, path, *, optional=False):
        try:
            if optional:
                try:
                    Path(path).stat()
                except FileNotFoundError:
                    return None
            return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, yaml.YAMLError):
            raise ValueError("invalid Discord intake configuration") from None


class ChannelRequests:
    def __init__(self, path, config, accounts, *, max_rows=1000):
        if type(max_rows) is not int or not 1 <= max_rows <= 1000:
            raise ValueError("invalid channel journal capacity")
        self.path, self.config, self.accounts, self.max_rows = Path(path), config, accounts, max_rows
        self.reply_outbox = None
        if any(not re.fullmatch(r"[0-9]{17,20}", user) or accounts.get(principal) != "operator"
               for user, principal in config.users.items()):
            raise ValueError("Discord users require currently registered operators")
        with closing(self._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_withdrawals (
                guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,message_id TEXT NOT NULL,
                reason TEXT NOT NULL,PRIMARY KEY(guild_id,channel_id,message_id))''')
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

    def current_receipt(self, receipt):
        self.operator(receipt['principal_id'])
        cfg = self.config
        if (cfg.users.get(receipt['author_id']) != receipt['principal_id']
                or receipt['guild_id'] != cfg.guild_id or receipt['channel_id'] != cfg.channel_id):
            raise HTTPException(403, detail='CHANNEL_OWNER_CHANGED')
        with closing(self._connect()) as conn:
            if conn.execute('SELECT 1 FROM fleet_channel_withdrawals WHERE guild_id=? AND channel_id=? AND message_id=?',
                            (receipt['guild_id'],receipt['channel_id'],receipt['message_id'])).fetchone():
                raise HTTPException(409,detail='CHANNEL_ORIGINAL_WITHDRAWN')

    def withdraw(self,guild_id,channel_id,message_id,reason='MESSAGE_CHANGED'):
        if ((guild_id,channel_id)!=(self.config.guild_id,self.config.channel_id)
                or re.fullmatch(r'[0-9]{17,20}',message_id) is None):
            return
        with closing(self._connect()) as conn,conn:
            conn.execute('''INSERT OR IGNORE INTO fleet_channel_withdrawals SELECT ?,?,?,?
                WHERE EXISTS (SELECT 1 FROM fleet_channel_requests WHERE guild_id=? AND channel_id=? AND message_id=?)''',
                         (guild_id,channel_id,message_id,reason,guild_id,channel_id,message_id))

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
                    conn.execute('INSERT OR IGNORE INTO fleet_channel_withdrawals VALUES (?,?,?,?)',
                                 (*scope,'MESSAGE_CHANGED'))
                    conn.commit()
                    raise HTTPException(409, detail="CHANNEL_MESSAGE_CHANGED")
                receipt = json.loads(old[1])
                self.current_receipt(receipt)
                if receipt["principal_id"] != principal:
                    raise HTTPException(403, detail="CHANNEL_OWNER_CHANGED")
                if self.reply_outbox is not None:
                    self.reply_outbox.received(conn, receipt)
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
            if self.reply_outbox is not None:
                self.reply_outbox.received(conn, receipt)
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


def install_channel_feature(app, *, config, task_service, principals, site_logins,
                            require_operator, read_guard, console, existing_tokens, secret_owners,
                            proposals=None, proposal_create=None, proposal_resolve=None, cell_prepare=None,
                            mission_admit=None, cell_service_id=None):
    if config is None:
        return
    if task_service is None:
        raise ValueError("Discord intake requires the existing tasks DB")
    key = config.transport_key
    token = None
    if config.bot_token_file is not None:
        try:
            token = Path(config.bot_token_file).read_text(encoding="utf-8").strip()
        except OSError:
            raise ValueError("Discord Bot credential file unavailable") from None
        if not re.fullmatch(r"[A-Za-z0-9_.-]{40,200}", token) or token == key:
            raise ValueError("invalid or shared Discord Bot credential")
    if config.replies_enabled and token is None:
        raise ValueError("Discord replies require a Bot credential")
    if config.hourly_health_enabled and token is None:
        raise ValueError("hourly Discord health requires a Bot credential")
    for credential in (key, token):
        if credential is None:
            continue
        if (hashlib.sha256(credential.encode()).hexdigest() in principals or credential in existing_tokens
                or console.uses_rest_token(credential) or console.uses_agent_pairing_token(credential)
                or any(owner is not None and owner.uses_token(credential) for owner in secret_owners)):
            raise ValueError("Discord transport credential must be isolated")
        for name in ("goal_evidence_service", "cell_goal_evidence_service"):
            service = getattr(app.state, name, None)
            if service is not None and any(producer.token == credential for producer in service.registry.producers):
                raise ValueError("Discord transport credential must be isolated")
    accounts = {p.principal_id: p.role for p in principals.values()}
    accounts.update({entry['principal_id']: entry['role'] for entry in (site_logins or {}).values()})
    app.state.channel_requests = ChannelRequests(task_service.store.path, config, accounts)
    install_channel_routes(app, app.state.channel_requests, require_operator=require_operator, read_guard=read_guard)
    from .workflow import ChannelWorkflow, install_workflow_routes
    app.state.channel_workflow = ChannelWorkflow(app.state.channel_requests, task_store=task_service.store)
    install_workflow_routes(app, app.state.channel_workflow, require_operator=require_operator, read_guard=read_guard,
                            task_service=task_service, console=console)
    from .missions import ChannelMissions, install_channel_mission_routes
    app.state.channel_missions = ChannelMissions(
        app.state.channel_workflow, proposals=proposals, proposal_create=proposal_create,
        proposal_resolve=proposal_resolve, cell_prepare=cell_prepare, mission_admit=mission_admit,
        cell_service_id=cell_service_id)
    install_channel_mission_routes(app, app.state.channel_missions, require_operator=require_operator,
                                   read_guard=read_guard)
    from .incidents import install_channel_incident_routes
    install_channel_incident_routes(app, app.state.channel_workflow, require_operator=require_operator,
                                    read_guard=read_guard)
    if token is not None:
        from .gateway import install_gateway
        install_gateway(app, app.state.channel_requests, token)
