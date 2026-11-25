"""Fleet HTTP routes for canonical cell-site recognition snapshots (`rosy.cell-site-recognition.v1`)."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response

from fleet.pipeline.cell_site_targets import list_canonical_sites

SCHEMA_ID = "rosy.cell-site-recognition.v1"
BODY_BYTES = 131072
MAX_SITES = 512
MAX_TEXT_LENGTH = 192
_DOCUMENT_FIELDS = frozenset({
    "schema", "snapshot_id", "observed_at", "source_id",
    "calibration_revision", "site_map_revision", "sites",
})
_SITE_FIELDS = frozenset({"site_ref", "state", "object_class", "object_ref_read", "confidence"})
_STATES = frozenset({"EMPTY", "OCCUPIED", "UNREADABLE"})
_UTC_ISO_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)"
)


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(422, detail={"code": code, "message": message})


def _clean_text(value: Any, *, field: str, limit: int = MAX_TEXT_LENGTH, code: str = "INVALID_SITE_RECOGNITION") -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise _bad(code, f"{field} requires clean text within {limit} characters")
    return value


def _validate_snapshot(payload: Any, *, known_site_refs: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _DOCUMENT_FIELDS:
        raise _bad("INVALID_SITE_RECOGNITION", "unknown or missing cell-site recognition fields")
    if payload["schema"] != SCHEMA_ID:
        raise _bad("INVALID_SITE_RECOGNITION", f"schema must be {SCHEMA_ID}")
    result: dict[str, Any] = {"schema": SCHEMA_ID}
    for field in ("snapshot_id", "source_id", "calibration_revision"):
        result[field] = _clean_text(payload[field], field=field)
    observed_at = _clean_text(payload["observed_at"], field="observed_at", limit=32)
    if not _UTC_ISO_RE.fullmatch(observed_at):
        raise _bad("INVALID_SITE_RECOGNITION", "observed_at must be a UTC ISO timestamp")
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        raise _bad("INVALID_SITE_RECOGNITION", "observed_at calendar timestamp is invalid") from None
    result["observed_at"] = observed_at
    rev = payload["site_map_revision"]
    if type(rev) is not int or rev < 1:
        raise _bad("INVALID_SITE_RECOGNITION", "site_map_revision must be a positive integer")
    result["site_map_revision"] = rev
    sites = payload["sites"]
    if not isinstance(sites, list) or len(sites) > MAX_SITES:
        raise _bad("INVALID_SITE_RECOGNITION", f"sites must be a list of at most {MAX_SITES} entries")
    seen: set[str] = set()
    validated_sites: list[dict[str, Any]] = []
    for entry in sites:
        if not isinstance(entry, dict) or set(entry) != _SITE_FIELDS:
            raise _bad("INVALID_SITE_RECOGNITION", "site entry has unknown or missing fields")
        site_ref = _clean_text(entry["site_ref"], field="site_ref", limit=96)
        if site_ref in seen:
            raise _bad("DUPLICATE_SITE_REF", f"duplicate site_ref {site_ref}")
        if site_ref not in known_site_refs:
            raise _bad("UNKNOWN_SITE_REF", f"site_ref {site_ref} is not in the canonical site map")
        seen.add(site_ref)
        state = entry["state"]
        if not isinstance(state, str) or state not in _STATES:
            raise _bad("INVALID_SITE_RECOGNITION", "state must be EMPTY, OCCUPIED or UNREADABLE")
        for opt in ("object_class", "object_ref_read"):
            if entry[opt] is not None:
                if state == "EMPTY":
                    raise _bad("INVALID_EMPTY_SITE", "EMPTY sites cannot carry object_class or object_ref_read")
                _clean_text(entry[opt], field=opt)
        confidence = entry["confidence"]
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1 or not math.isfinite(confidence):
            raise _bad("INVALID_SITE_RECOGNITION", "confidence must be finite in 0..1")
        validated_sites.append({
            "site_ref": site_ref,
            "state": state,
            "object_class": entry["object_class"],
            "object_ref_read": entry["object_ref_read"],
            "confidence": float(confidence),
        })
    result["sites"] = validated_sites
    return result


def install_cell_site_recognition_routes(app, *, service, require_viewer, authorize=None,
                                         web_common: Path | None = None) -> None:
    """Install read-only GET and validated POST routes for `rosy.cell-site-recognition.v1`."""

    @app.get("/api/fleet/cell-site-recognition", tags=["workcell-observations"])
    def get_cell_site_recognition(response: Response, _principal=Depends(require_viewer)):
        response.headers["Cache-Control"] = "no-store"
        snapshot = getattr(app.state, "cell_site_recognition", None)
        if snapshot is None:
            raise HTTPException(404, detail={"code": "CELL_SITE_RECOGNITION_NOT_YET_OBSERVED",
                                             "message": "no cell-site recognition snapshot published yet"})
        return deepcopy(snapshot)

    @app.post("/api/fleet/cell-site-recognition", tags=["workcell-observations"])
    async def post_cell_site_recognition(
        request: Request,
        response: Response,
        token: str | None = Header(None, alias="X-Workcell-Observation-Token"),
        authorization: str | None = Header(default=None),
    ):
        response.headers["Cache-Control"] = "no-store"
        if token is not None:
            if service is None or not service.uses_token(token):
                raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"})
        elif authorize is not None:
            principal = authorize(request, authorization)
            if not principal.permits_site("fleet.operate", {"operator", "service"}):
                raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "operator or service role required"})
        else:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"})

        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > BODY_BYTES:
                raise HTTPException(413, detail={"code": "SITE_RECOGNITION_TOO_LARGE"})
            raw.extend(chunk)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _bad("INVALID_SITE_RECOGNITION", "body must be valid JSON") from None

        known_refs = {s["wire_ref"] for s in list_canonical_sites(web_common)["sites"]}
        snapshot = _validate_snapshot(payload, known_site_refs=known_refs)
        app.state.cell_site_recognition = deepcopy(snapshot)
        return {
            "ok": True,
            "snapshot_id": snapshot["snapshot_id"],
            "site_count": len(snapshot["sites"]),
            "snapshot": deepcopy(snapshot),
        }
