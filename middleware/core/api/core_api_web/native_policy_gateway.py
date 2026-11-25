"""TLS-only CORE ingress for a separately enrolled, same-host native policy lease owner.

Fleet GET /api/v1/arm/lease-status checks the owner without creating a grant. On a native
target, Fleet POSTs {workcell_id, scope} to /lease-challenge *before* minting each grant,
then includes the returned challenge and approved scope in the normal /lease body.
Scope identifies exactly one cell-task:<task_id>:arm_b. The gateway's one-use challenge
ties the task to an owner boot session and caps TTL on the host monotonic clock.
HOLD discards the pending challenge even if the native owner cannot confirm the stop.

The local arm socket uses Linux SO_PEERCRED, a private shared group and one JSON line per
connection (8 KiB maximum). Status is {op: status}; lease is {op: lease, owner_session_id,
not_after_monotonic_ns, grant}; hold is {op: hold, reason}. The owner independently enforces
pins, episode replay protection and the earlier monotonic grant deadline. Only a physically
confirmed HOLD may reply with accepted=true, motor_hold_confirmed=true and a hold_reason.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import threading
import time
from types import SimpleNamespace
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.errors import ApiError, register_exception_handlers
from core_api_web.api.v1.arm import ArmHoldRequest, ArmLeaseGrant, Text, arm_caller


def exchange(path, owner_uid, request):
    """Both ends authenticate the Unix peer. The owner has a distinct service uid."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        deadline = time.monotonic() + 0.15
        client.settimeout(0.15)
        client.connect(path)
        _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != owner_uid:
            raise PermissionError("owner credential mismatch")
        wire = json.dumps(request, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(wire) > 8192:
            raise ValueError("oversize owner request")
        client.sendall(wire)
        buf = bytearray()
        while not buf.endswith(b"\n"):
            left = deadline - time.monotonic()
            if left <= 0 or len(buf) >= 8192:
                raise ValueError("invalid owner reply")
            client.settimeout(left)
            block = client.recv(8192 - len(buf))
            if not block:
                raise ValueError("incomplete owner reply")
            buf.extend(block)
        reply = json.loads(buf)
        if not isinstance(reply, dict):
            raise ValueError("invalid owner reply")
        return reply


Scope = Annotated[str, Field(min_length=1, max_length=256)]


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workcell_id: Text
    scope: Scope


class NativeGrant(ArmLeaseGrant):
    scope: Scope
    challenge: Text


class NativeRelay:
    def __init__(self, cfg, *, connect=exchange, clock=time.monotonic_ns):
        self.workcell, self.arm = cfg["workcell_id"], cfg["arm_id"]
        self.path, self.uid = cfg["socket_path"], cfg["owner_uid"]
        if (self.arm != "arm_b" or not self.workcell
                or not os.path.isabs(self.path) or type(self.uid) is not int
                or self.uid <= 0 or os.geteuid() in (0, self.uid)):
            raise ValueError("invalid native policy owner configuration")
        self.connect, self.clock = connect, clock
        self.lock = threading.Lock()
        self.pending = None

    def send(self, request):
        try:
            return self.connect(self.path, self.uid, request)
        except (OSError, ValueError, RecursionError):
            raise ApiError("NATIVE_POLICY_OWNER_UNAVAILABLE", 503) from None

    def status(self):
        try:
            owner = self.send({"op": "status"})
        except ApiError:
            return dict(workcell_id=self.workcell, arm_id=self.arm, ready=False, reason="owner_unavailable")
        session = owner.get("owner_session_id")
        if (owner.get("arm_id") != self.arm or not isinstance(session, str)
                or not 1 <= len(session) <= 128 or not session.isprintable()):
            return dict(workcell_id=self.workcell, arm_id=self.arm, ready=False, reason="owner_binding_mismatch")
        ready = owner.get("ready") is True
        reason = owner.get("reason")
        if not isinstance(reason, str) or not re.fullmatch(r"[a-z0-9_]{1,96}", reason):
            reason = "owner_not_armed"
        return dict(workcell_id=self.workcell, arm_id=self.arm, ready=ready, owner_session_id=session,
                    reason=None if ready else reason)

    def challenge(self, req):
        with self.lock:
            self.pending = None
            if (req.workcell_id != self.workcell
                    or not re.fullmatch(r"cell-task:(?!-)(?![^:]*\.\.)[A-Za-z0-9._@-]{1,128}:" + self.arm, req.scope)):
                raise ApiError("NATIVE_POLICY_SCOPE_MISMATCH", 409)
            status = self.status()
            if not status["ready"]:
                raise ApiError("NATIVE_POLICY_OWNER_NOT_READY", 409, status["reason"])
            nonce = secrets.token_hex(32)
            self.pending = (nonce, self.clock(), req.scope, status["owner_session_id"])
            return {"challenge": nonce}

    def deliver(self, grant):
        with self.lock:
            pending, self.pending = self.pending, None
            if (not pending or not secrets.compare_digest(pending[0].encode(), grant.challenge.encode())
                    or self.workcell != grant.workcell_id or pending[2] != grant.scope):
                raise ApiError("NATIVE_POLICY_CHALLENGE_REFUSED", 409)
            deadline = pending[1] + int(min(grant.ttl_s, grant.window_remaining_s) * 1e9)
            if self.clock() >= deadline:
                raise ApiError("NATIVE_POLICY_GRANT_EXPIRED", 409)
            reply = self.send(dict(op="lease", grant=grant.model_dump(exclude={"challenge"}),
                                   owner_session_id=pending[3], not_after_monotonic_ns=deadline))
            expires = reply.get("lease_expires_at_ns")
            if reply.get("accepted") is not True or type(expires) is not int or not self.clock() < expires <= deadline:
                raise ApiError("NATIVE_POLICY_GRANT_REFUSED", 409)
            return {"accepted": True, "lease_expires_at_ns": expires}

    def hold(self, reason):
        with self.lock:
            self.pending = None
            reply = self.send({"op": "hold", "reason": reason})
            if (reply.get("accepted") is not True or reply.get("motor_hold_confirmed") is not True
                    or not isinstance(reply.get("hold_reason"), str) or not reply["hold_reason"]):
                raise ApiError("NATIVE_POLICY_HOLD_UNCONFIRMED", 409)
            return {"hold_reason": reply["hold_reason"]}


def create_app(cfg, *, relay=None):
    principal, digest = cfg["fleet_principal"], cfg["token_sha256"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", principal) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid Fleet lease principal configuration")
    token = dict(id=principal, sha256=digest, role="operator", source="configured")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.core = SimpleNamespace(config={"auth": {"tokens": [token]}})
    register_exception_handlers(app)
    relay = relay or NativeRelay(cfg)

    def fleet(auth=Depends(arm_caller)):
        if auth.token_id != principal:
            raise ApiError("ARM_POLICY_FORBIDDEN", 403)

    prefix = "/api/v1/arm/"
    guards = [Depends(fleet)]

    @app.get(prefix + "lease-status", dependencies=guards)
    def status():
        return relay.status()

    @app.post(prefix + "lease-challenge", dependencies=guards)
    def challenge(body: ChallengeRequest):
        return relay.challenge(body)

    @app.post(prefix + "lease", dependencies=guards)
    def grant(body: NativeGrant):
        return relay.deliver(body)

    @app.post(prefix + "hold", dependencies=guards)
    def hold(body: ArmHoldRequest):
        return relay.hold(body.reason)

    return app


def main():
    import uvicorn
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "host", "certfile", "keyfile"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--port", type=int, required=True)
    args = p.parse_args()
    app = create_app(json.loads(Path(args.config).read_text(encoding="utf-8")))
    uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=args.certfile, ssl_keyfile=args.keyfile,
                proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
