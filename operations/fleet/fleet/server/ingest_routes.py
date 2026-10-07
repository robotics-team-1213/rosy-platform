"""사이트 섭취(ingest) 표면 — 발견 스캔, 목격(sighting), 정책 증거, CORE 이벤트.

기기·관측 서비스가 Fleet 에 데이터를 밀어 넣는 경로와 그 읽기. 각 서비스는 자기
자격을 검증하고 라우트보다 먼저 겹침을 거절한다(D-302 자격 분리).
"""

from __future__ import annotations

import hmac
import logging
import sqlite3
from hashlib import sha256
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Query

from core_common.protocol.policy_evidence import PolicyEvidencePayload
from core_common.protocol.schemas import DiscoveryScanPayload
from core_common.protocol.network_peers import PeerObservation
from core_common.protocol.sightings import SiteSightingPayload
from fleet.server.address_drift import classify_addresses
from fleet.server.policy_evidence import PolicyEvidenceError, status_code_for
from fleet.server.sightings import SightingError

_LOG = logging.getLogger(__name__)


def address_reasons(*, console, hub, discovery, enrollment) -> dict:
    """Each pinned robot vs the latest scan (D-361 3, D-370 5.3); explains, never follows."""
    identities = hub.registry.identity_snapshot() if hub is not None else {}
    enrolled = enrollment.enrolled_names() if enrollment is not None else {}
    snapshot = discovery.snapshot(console.registered_endpoints, identities, enrolled)
    pinned = console.registered_endpoints
    listing = enrollment.listing() if enrollment is not None else None
    static_ids = set(listing["static_robot_ids"]) if listing is not None else set(pinned)
    movable = {row["robot_id"] for row in (listing or {}).get("robots", ())
               if row["state"] == "address_changed" and row.get("hold") != "conflict"}
    names = {robot_id: name for name, robot_id in enrolled.items()}
    for robot_id in static_ids & set(pinned):
        # A static robot's identity: its authenticated HELLO name, else its own `.local` name.
        host = (urlsplit(pinned[robot_id]).hostname or "").lower()
        device_name = (identities.get(robot_id) or {}).get("device_name")
        if device_name:
            names[robot_id] = str(device_name).lower()
        elif host.endswith(".local"):
            names[robot_id] = host.removesuffix(".local")
    result = classify_addresses(pinned, snapshot["devices"] if snapshot["scanner_online"] else None,
                                names=names, movable=movable)
    for entry in result["robots"]:
        entry["origin"] = "static" if entry["robot_id"] in static_ids else "enrolled"
    result["scanner_state"] = snapshot["scanner_state"]
    return result


def install_discovery_routes(app, *, console, hub, discovery, discovery_token,
                             enrollment, principals, require_viewer, read_guard, catalogue=None) -> None:
    if principals and any(hmac.compare_digest(
            sha256(discovery_token.encode("utf-8")).hexdigest(), digest)
            for digest in principals):
        raise ValueError("discovery credential must differ from site user credentials")

    @app.post("/api/fleet/discovery/scan", tags=["fleet-discovery"])
    async def discovery_scan(body: DiscoveryScanPayload,
                             authorization: Optional[str] = Header(default=None)) -> dict:
        expected = f"Bearer {discovery_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
        try:
            if catalogue is not None:
                services = catalogue.validate_scan(body.services, services_only=True)
            discovery.replace_scan(body.devices)
            if catalogue is not None:
                robots = [PeerObservation(name=row['name'], role='robot',
                          transport=row.get('transport', 'http'), service_type='_rosy._tcp',
                          hostname=row['hostname'], address=row['address'], port=row['port'])
                          for row in discovery.rows() if row['hostname']]
                services.extend(robots)
                catalogue.replace_scan(services)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_SCAN",
                                                         "message": str(exc)}) from exc
        if enrollment is not None and enrollment.available:
            await enrollment.on_discovery(discovery.rows())
            await enrollment.settle_holds()
        _warn_static_drift()
        return {"accepted": True}

    warned: set[tuple[str, str]] = set()

    def _warn_static_drift() -> None:
        """robots.yaml endpoints are never rewritten here; the log names the stale one once."""
        current = set()
        for entry in address_reasons(console=console, hub=hub, discovery=discovery,
                                     enrollment=enrollment)["robots"]:
            if entry["origin"] != "static":
                continue
            if entry["status"] == "outside_scanned_subnets":
                key = (entry["robot_id"], entry["status"])
                message = ("static robot %s pinned at %s is outside every scanned subnet; "
                           "robots.yaml base_url may be stale")
                args = (entry["robot_id"], entry["pinned"])
            elif entry["status"] == "seen_at_other_address":
                key = (entry["robot_id"], ",".join(entry["seen_addresses"]))
                message = ("static robot %s pinned at %s is seen at %s; not followed (D-370 5.3) "
                           "- confirm and edit robots.yaml")
                args = (entry["robot_id"], entry["pinned"], ", ".join(entry["seen_addresses"]))
            else:
                continue
            current.add(key)
            if key not in warned:
                _LOG.warning(message, *args)
        warned.clear()
        warned.update(current)

    @app.get("/api/fleet/discovery/addresses", dependencies=read_guard,
             tags=["fleet-discovery"])
    def discovery_addresses() -> dict:
        return address_reasons(console=console, hub=hub, discovery=discovery,
                               enrollment=enrollment)

    @app.get("/api/fleet/discovery", dependencies=read_guard,
             tags=["fleet-discovery"])
    def discovery_readback() -> dict:
        identities = hub.registry.identity_snapshot() if hub is not None else {}
        enrolled = enrollment.enrolled_names() if enrollment is not None else {}
        return discovery.snapshot(console.registered_endpoints, identities, enrolled)


def install_ingest_routes(app, *, console, console_token, hub, sightings,
                          policy_evidence, principals, require_viewer, read_guard,
                          map_pose=None) -> None:
    if sightings is not None and sightings.enabled:
        if console_token is not None and sightings.uses_token(console_token):
            raise ValueError("sighting source credentials must differ from the console token")
        if principals and sightings.reuses_any(
                lambda candidate: any(
                    hmac.compare_digest(sha256(candidate.encode("utf-8")).hexdigest(), digest)
                    for digest in principals)):
            raise ValueError("site user and sighting credentials must differ")
        if sightings.reuses_any(console.uses_rest_token):
            raise ValueError("sighting source credentials must differ from robot REST tokens")
        if sightings.reuses_any(console.uses_agent_pairing_token):
            raise ValueError("sighting source credentials must differ from CORE Agent pairing tokens")

        @app.post("/api/fleet/sightings", tags=["sightings"])
        async def submit_sighting(body: SiteSightingPayload,
                                  authorization: Optional[str] = Header(default=None)) -> dict:
            try:
                row = sightings.accept(authorization, body)
            except SightingError as exc:
                raise HTTPException(status_code=exc.status_code,
                                    detail={"code": exc.code, "message": str(exc)}) from exc
            if map_pose is not None:   # D-491 3: only an accepted sighting anchors the map pose
                map_pose.observe_sighting(row)
            return row

        @app.get("/api/fleet/sightings", dependencies=read_guard, tags=["sightings"])
        async def sighting_readback() -> dict:
            return sightings.snapshot()

    if policy_evidence is not None:
        if console_token is not None and policy_evidence.uses_token(console_token):
            raise ValueError("policy evidence credentials must differ from the console token")
        if principals and policy_evidence.reuses_any(
                lambda candidate: any(
                    hmac.compare_digest(sha256(candidate.encode("utf-8")).hexdigest(), digest)
                    for digest in principals)):
            raise ValueError("site user and policy evidence credentials must differ")
        if policy_evidence.reuses_any(console.uses_rest_token):
            raise ValueError("policy evidence credentials must differ from robot REST tokens")
        if policy_evidence.reuses_any(console.uses_agent_pairing_token):
            raise ValueError("policy evidence credentials must differ from CORE Agent pairing tokens")

        @app.post("/api/fleet/policy-evidence", tags=["policy-evidence"])
        async def submit_policy_evidence(body: PolicyEvidencePayload,
                                         authorization: Optional[str] = Header(default=None)) -> dict:
            try:
                return policy_evidence.accept(authorization, body)
            except PolicyEvidenceError as exc:
                reason = str(exc).split(":", 1)[0].strip()
                raise HTTPException(status_code=status_code_for(reason),
                                    detail={"code": reason,
                                            "message": "policy evidence was not accepted"}) from exc

        @app.get("/api/fleet/policy-evidence/latest", dependencies=read_guard,
                 tags=["policy-evidence"])
        async def policy_evidence_readback() -> dict:
            return {"evidence": policy_evidence.latest()}

    if hub is not None and hub.event_store is not None:
        @app.get("/api/fleet/events", dependencies=read_guard, tags=["fleet-events"])
        def core_event_history(
            after_id: int = Query(default=0, ge=0),
            limit: int = Query(default=100, ge=1, le=200),
            robot_id: Optional[str] = Query(default=None, min_length=1, max_length=96),
        ) -> dict:
            try:
                rows = hub.event_store.read_events(after_id=after_id, limit=limit,
                                                   robot_id=robot_id)
            except (OSError, sqlite3.Error):
                raise HTTPException(status_code=503, detail={
                    "code": "EVENT_STORAGE_UNAVAILABLE",
                    "message": "CORE event history is temporarily unavailable",
                }) from None
            page = rows[:limit]
            return {
                "events": page,
                "next_cursor": page[-1]["audit_id"] if page else after_id,
                "has_more": len(rows) > limit,
            }
