"""D-992: Fleet delivers this robot's Account receiver settings over TLS, applied without a restart.

Only public values arrive. The encryption key is made here and never leaves. Owner: `account_sessions`;
this path touches people's login only, never the drive path or the FleetAgent.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import viewer
from core_api_web.api.v1.fleet_link import link_seat
from core_common.config import account_receiver_path, write_private
from core_common.protocol.account_client import load_account_client

account_receiver_router = APIRouter(prefix="/api/v1/account/receiver", tags=["account-receiver"])

CALLBACK_PATH = "/api/account/callback"


class AccountReceiverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    issuer: str = Field(max_length=512)
    client_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,96}$")
    callback: str = Field(max_length=512)
    public_keys: dict[str, str] = Field(min_length=1, max_length=8)


def load_provisioned(robot_id: str):
    """The received settings at boot, or None. A damaged file never stops CORE (D-992 7)."""
    path = account_receiver_path()
    if not path.exists():
        return None
    try:
        client = load_account_client(path)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return client if client.resource == "robot:" + robot_id else None


def _public_pem(pem: str) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data = pem.encode("ascii")
    if not isinstance(load_pem_public_key(data), Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return data


def _write(body: AccountReceiverRequest, robot_id: str) -> Path:
    from cryptography.fernet import Fernet

    path = account_receiver_path()
    keys = {}
    for number, (kid, pem) in enumerate(sorted(body.public_keys.items())):
        name = f"account-key-{number}.pem"
        write_private(path.with_name(name), _public_pem(pem).decode("ascii"))
        keys[kid] = name
    secret = path.with_name("account-session.key")
    if not secret.exists():  # keep it: replacing it would sign out everyone logged in on this robot
        write_private(secret, Fernet.generate_key().decode("ascii"))
    write_private(path, json.dumps({
        "issuer": body.issuer, "client_id": body.client_id, "resource": "robot:" + robot_id,
        "callback": body.callback, "public_key_files": keys, "encryption_key_file": secret.name,
        "session_db": "account-sessions.sqlite3"}))
    return path


def _readback(request: Request, svc: CoreServicesLike) -> dict:
    client = getattr(request.app.state, "account_client", None)
    return {"configured": client is not None,
            "managed": bool(svc.config.get("auth", {}).get("account_client_file")),
            "client_id": client.client_id if client else None,
            "issuer": client.issuer if client else None,
            "resource": client.resource if client else None}


@account_receiver_router.get("")
def account_receiver(request: Request, _: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _readback(request, svc)


@account_receiver_router.put("")
async def put_account_receiver(request: Request, auth: AuthContext = Depends(link_seat),
                               svc: CoreServicesLike = Depends(get_services)):
    try:
        body = AccountReceiverRequest.model_validate_json(await request.body())
    except ValueError:
        raise ApiError("VALIDATION_ERROR", 400, "body must be {issuer, client_id, callback, public_keys}") from None
    if svc.config.get("auth", {}).get("account_client_file"):
        raise ApiError("ACCOUNT_RECEIVER_MANAGED", 409, "this robot's operator set auth.account_client_file")
    from urllib.parse import urlsplit
    if urlsplit(body.callback).path != CALLBACK_PATH:
        raise ApiError("VALIDATION_ERROR", 400, "callback must be CORE's Account callback")
    path = account_receiver_path()
    previous = path.read_bytes() if path.exists() else None
    try:
        client = load_account_client(_write(body, svc.identity.robot_id))
    except (ValueError, UnicodeError, KeyError, TypeError):
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            write_private(path, previous.decode("utf-8"))
        raise ApiError("VALIDATION_ERROR", 400, "the Account settings were refused") from None
    except OSError as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to write the Account settings: {exc.strerror}") from None
    request.app.state.account_client = client
    svc.events.publish("account.receiver_provisioned", severity="warning", source="api",
                       data={"by": auth.token_id, "client_id": body.client_id})
    return _readback(request, svc)
