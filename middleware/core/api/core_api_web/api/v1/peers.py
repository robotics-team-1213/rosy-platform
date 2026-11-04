"""core_api_web.api.v1.peers — peer pose sharing (no-topview fallback).

Design: docs/plans/2026-11-04-peer-pose-sharing-design.md. The beacon route
is the trust boundary: only a `PEER_SHARE`-granted session may post, and the
manager only keeps what a beacon actually claimed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.grants import PEER_SHARE, require_grant
from core_api_web.api.v1.common import viewer
from core_common.protocol.schemas import PeerBeacon

peers_router = APIRouter(prefix="/api/v1/peers", tags=["peers"])


@peers_router.get("")
def list_peers(_: AuthContext = Depends(viewer),
               svc: CoreServicesLike = Depends(get_services)):
    return {"peers": [row.model_dump() for row in svc.peers.snapshot()]}


@peers_router.post("/beacon", status_code=202)
def accept_beacon(body: PeerBeacon,
                  _: AuthContext = Depends(require_grant(PEER_SHARE)),
                  svc: CoreServicesLike = Depends(get_services)):
    """A stale or duplicate seq is still answered 202 — it is a no-op, not an error."""
    return {"accepted": True, "updated": bool(svc.peers.observe(body))}
