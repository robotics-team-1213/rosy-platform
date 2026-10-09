"""D-555: Fleet delivers this robot's hub pairing credential over TLS.

`PUT /fleet/link` writes the private link file (0600) and restarts only the
FleetAgent; `DELETE` removes it. `GET` never returns the token. The token is
held only for the request and never logged or published. Owner: `fleet_agent`.
"""

from __future__ import annotations

import ssl

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_common.config import (
    FLEET_LINK_KEYS,
    ConfigError,
    clear_fleet_link,
    fleet_link_layer,
    load_config,
    merge_fleet_link,
    write_fleet_link,
)
from core_common.protocol.discovery_txt import HOSTNAME

fleet_link_router = APIRouter(prefix="/api/v1/fleet/link", tags=["fleet-link"])

#: Screen-code sources; Fleet's enrollment token is one of these with a `site:` label.
_CODE_SOURCES = frozenset({"pair-physical", "pair-admin"})
MAX_CA_BYTES = 16384


class FleetLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_token: str = Field(min_length=32, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    expected_hostname: str = Field(max_length=253)
    ca_pem: str = Field(min_length=1, max_length=MAX_CA_BYTES)


def link_seat(request: Request, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)) -> AuthContext:
    """D-555 3: CORE's own TLS listener, and an administrator or Fleet's site enrollment token.

    The `site:` label is what Fleet sets at enrollment; it narrows the seat, it does not
    authenticate (any operator who pairs by screen code can choose it).
    """
    if request.url.scheme != "https" or not (svc.config.get("network") or {}).get("tls"):
        raise ApiError("TLS_REQUIRED", 403, "fleet link provisioning requires authenticated HTTPS")
    site_token = auth.source in _CODE_SOURCES and auth.label.startswith("site:")
    if auth.shared_dev or not (auth.role == "administrator" or site_token):
        raise ApiError("FORBIDDEN", 403, "requires administrator or the site enrollment token")
    return auth


def _readback(svc: CoreServicesLike) -> dict:
    fleet = svc.config.get("fleet") or {}
    agent = svc.fleet_agent
    discovery = fleet.get("discovery") if isinstance(fleet.get("discovery"), dict) else {}
    return {
        "configured": bool(fleet.get("pairing_token")) and bool(discovery or fleet.get("hub_url")),
        "provisioned": fleet_link_layer() is not None,
        "expected_hostname": discovery.get("expected_hostname"),
        "hub_url": fleet.get("hub_url"),
        "enabled": bool(agent.enabled),
        "connected": bool(agent.connected),
        "fleet_goal_active": svc.nav.fleet_goal() is not None,
    }


def _refuse_during_fleet_goal(svc: CoreServicesLike) -> None:
    """D-555 review: a relink drops the link; with a Fleet goal running that would arm SAF-003."""
    if svc.nav.fleet_goal() is not None:
        raise ApiError("FLEET_GOAL_ACTIVE", 409,
                       "a Fleet navigation goal is running; change the Fleet link after it ends")


@fleet_link_router.get("")
def fleet_link(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _readback(svc)


# async: FleetAgent.relink must run on the API event loop (its task lives there).
@fleet_link_router.put("")
async def put_fleet_link(request: Request, auth: AuthContext = Depends(link_seat),
                         svc: CoreServicesLike = Depends(get_services)):
    try:
        body = FleetLinkRequest.model_validate_json(await request.body())
    except ValueError:
        # No field detail: pydantic's errors echo the input, and the input is the token.
        raise ApiError("VALIDATION_ERROR", 400,
                       "body must be {pairing_token, expected_hostname, ca_pem}") from None
    _refuse_during_fleet_goal(svc)
    fallback = (getattr(svc.fleet_agent, "config_fallback", None)
                or getattr(svc.fleet_loss, "config_fallback", None))
    if fallback:
        raise ApiError("FLEET_LINK_CONFIG_INVALID", 409,
                       f"boot used defaults for an invalid Fleet setting ({fallback}); fix it and restart CORE")
    hostname = body.expected_hostname.lower().rstrip(".")
    if not HOSTNAME.fullmatch(hostname):
        raise ApiError("VALIDATION_ERROR", 400, "expected_hostname must be an approved .local name")
    try:
        ssl.create_default_context(cadata=body.ca_pem)
    except (ssl.SSLError, ValueError):
        raise ApiError("VALIDATION_ERROR", 400, "ca_pem is not a PEM certificate") from None
    try:
        link = write_fleet_link(body.pairing_token, hostname, body.ca_pem)
    except OSError as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to write the fleet link: {exc.strerror}") from None
    svc.fleet_agent.relink(merge_fleet_link(svc.config.get("fleet"), link))
    svc.events.publish("fleet.link_provisioned", severity="warning", source="api",
                       data={"by": auth.token_id, "expected_hostname": hostname})
    return _readback(svc)


@fleet_link_router.delete("")
async def delete_fleet_link(auth: AuthContext = Depends(link_seat),
                            svc: CoreServicesLike = Depends(get_services)):
    _refuse_during_fleet_goal(svc)
    try:
        removed = clear_fleet_link()
        lower = load_config(fleet_link=False).get("fleet") or {}
    except (OSError, ConfigError, ValueError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to clear the fleet link: {type(exc).__name__}") from None
    # Back to whatever link the lower layers held (usually none).
    fallback = {key: lower[key] for key in FLEET_LINK_KEYS if key in lower}
    svc.fleet_agent.relink(merge_fleet_link(svc.config.get("fleet"), fallback))
    svc.events.publish("fleet.link_cleared", severity="warning", source="api",
                       data={"by": auth.token_id, "removed": removed})
    return {**_readback(svc), "removed": removed}
