"""D-992: Fleet delivers this robot's Account receiver settings over TLS, applied without a restart.

Choosing the issuer and keys chooses who may sign robot.admin here, so a site token may only deliver
what the robot's operator pinned in `auth.account_trust`; anything else needs an administrator.
The encryption key is made here and never leaves. This path touches people's login only, never the
drive path or the FleetAgent. File and sqlite work runs off the event loop the FleetAgent lives on.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import viewer
from core_api_web.api.v1.fleet_link import link_seat
from core_common.config import account_receiver_path, write_private
from core_common.protocol.account_client import AccountUnavailable, load_account_client

account_receiver_router = APIRouter(prefix="/api/v1/account/receiver", tags=["account-receiver"])

CALLBACK_PATH = "/api/account/callback"
_APPLY_LOCK = threading.Lock()  # concurrent deliveries must not prune each other's key files


class AccountReceiverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    issuer: str = Field(max_length=512)
    client_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,96}$")
    callback: str = Field(max_length=512)
    public_keys: dict[str, str] = Field(min_length=1, max_length=8)


def load_provisioned(robot_id: str):
    """The received settings at boot, or None. Nothing in this optional file may stop CORE (D-992 7)."""
    path = account_receiver_path()
    if not path.exists():
        return None
    try:
        client = load_account_client(path)
    except (OSError, ValueError, KeyError, TypeError, AccountUnavailable):
        return None
    return client if client.resource == "robot:" + robot_id else None


def _public_pem(pem: str) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data = pem.encode("ascii")
    if not isinstance(load_pem_public_key(data), Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return data


def _digest(pem: str) -> str:
    return sha256(pem.encode("ascii")).hexdigest()


def _pinned(svc: CoreServicesLike, body: AccountReceiverRequest) -> bool:
    trust = svc.config.get("auth", {}).get("account_trust")
    if not isinstance(trust, dict) or trust.get("issuer") != body.issuer:
        return False
    allowed = trust.get("public_key_sha256")
    return isinstance(allowed, list) and all(_digest(pem) in allowed for pem in body.public_keys.values())


def _session_db(issuer: str, client_id: str) -> str:
    """One database per issuer and client: another issuer can never read a stored refresh token."""
    return f"account-sessions-{sha256(f'{issuer} {client_id}'.encode()).hexdigest()[:16]}.sqlite3"


def _previous(path: Path) -> tuple[bytes | None, dict]:
    if not path.exists():
        return None, {}
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw)
    except ValueError:  # a damaged file must not block the delivery that repairs it
        return raw, {}
    return raw, parsed if isinstance(parsed, dict) else {}


def _remove_quietly(paths) -> None:
    """Leftovers only: the new settings already work, so a failed removal must not fail the delivery."""
    for stale in paths:
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def _apply(body: AccountReceiverRequest, robot_id: str):
    from cryptography.fernet import Fernet

    pems = {kid: _public_pem(pem).decode("ascii") for kid, pem in body.public_keys.items()}
    path = account_receiver_path()
    previous, old = _previous(path)
    database = _session_db(body.issuer, body.client_id)
    # Content-named, so a refused delivery can never leave the working settings pointing at new keys.
    names = {kid: f"account-key-{_digest(pem)[:16]}.pem" for kid, pem in pems.items()}
    for kid, pem in pems.items():
        write_private(path.with_name(names[kid]), pem)
    secret = path.with_name("account-session.key")
    if not secret.exists():  # keep it: replacing it would sign out everyone logged in on this robot
        write_private(secret, Fernet.generate_key().decode("ascii"))
    write_private(path, json.dumps({
        "issuer": body.issuer, "client_id": body.client_id, "resource": "robot:" + robot_id,
        "callback": body.callback, "public_key_files": names, "encryption_key_file": secret.name,
        "session_db": database}))
    try:
        client = load_account_client(path)
    except Exception:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            write_private(path, previous.decode("utf-8"))
        raise
    _remove_quietly(stale for stale in path.parent.glob("account-key-*.pem") if stale.name not in names.values())
    _remove_quietly(stale for stale in path.parent.glob("account-sessions-*")
                    if not stale.name.startswith(database))
    return client


def _locked_apply(body: AccountReceiverRequest, robot_id: str):
    with _APPLY_LOCK:
        return _apply(body, robot_id)


def _clear() -> None:
    path = account_receiver_path()
    with _APPLY_LOCK:
        path.unlink(missing_ok=True)
        _remove_quietly([*path.parent.glob("account-sessions-*"), *path.parent.glob("account-key-*.pem")])


def _readback(request: Request, svc: CoreServicesLike) -> dict:
    client = getattr(request.app.state, "account_client", None)
    return {"configured": client is not None,
            "managed": bool(svc.config.get("auth", {}).get("account_client_file")),
            "client_id": client.client_id if client else None,
            "issuer": client.issuer if client else None,
            "resource": client.resource if client else None}


def _refuse_if_managed(svc: CoreServicesLike) -> None:
    if svc.config.get("auth", {}).get("account_client_file"):
        raise ApiError("ACCOUNT_RECEIVER_MANAGED", 409, "this robot's operator set auth.account_client_file")


@account_receiver_router.get("")
def account_receiver(request: Request, _: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _readback(request, svc)


@account_receiver_router.put("")
async def put_account_receiver(request: Request, auth: AuthContext = Depends(link_seat),
                               svc: CoreServicesLike = Depends(get_services)):
    try:
        body = AccountReceiverRequest.model_validate_json(await request.body())
        parsed, issuer = urlsplit(body.callback), urlsplit(body.issuer)
        for url in (parsed, issuer):
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Account URLs must be fixed HTTPS URLs")
        for pem in body.public_keys.values():
            _public_pem(pem)
    except (ValueError, UnicodeError):
        raise ApiError("VALIDATION_ERROR", 400, "body must be {issuer, client_id, callback, public_keys}") from None
    # A typo guard, not authentication (Host is the caller's): the Account registry decides what is trusted.
    if parsed.path != CALLBACK_PATH or parsed.netloc != request.headers.get("host"):
        raise ApiError("VALIDATION_ERROR", 400, "callback must be this listener's Account callback")
    _refuse_if_managed(svc)
    if auth.role != "administrator" and not (_pinned(svc, body) and body.client_id == "robot-" + svc.identity.robot_id):
        raise ApiError("ACCOUNT_TRUST_UNPINNED", 403, "this issuer, keys and client are not pinned for this robot")
    try:
        client = await run_in_threadpool(_locked_apply, body, svc.identity.robot_id)
    except (OSError, AccountUnavailable, ValueError, KeyError, TypeError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to apply the Account settings: {type(exc).__name__}") from None
    request.app.state.account_client = client
    svc.events.publish("account.receiver_provisioned", severity="warning", source="api",
                       data={"by": auth.token_id, "client_id": body.client_id})
    return _readback(request, svc)


@account_receiver_router.delete("")
async def delete_account_receiver(request: Request, auth: AuthContext = Depends(link_seat),
                                  svc: CoreServicesLike = Depends(get_services)):
    """Administrator only: a robot leaving a site stops trusting its issuer. The private key stays unused."""
    if auth.role != "administrator":
        raise ApiError("FORBIDDEN", 403, "requires administrator")
    _refuse_if_managed(svc)
    try:
        await run_in_threadpool(_clear)
    except OSError as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to clear the Account settings: {type(exc).__name__}") from None
    request.app.state.account_client = None
    svc.events.publish("account.receiver_cleared", severity="warning", source="api", data={"by": auth.token_id})
    return _readback(request, svc)
