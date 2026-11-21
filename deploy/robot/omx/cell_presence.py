"""D-1057/D-911: the supervised-first-run switch, the review-required finding and the zone acceptance of a task.

`presence_ok`: only a task a named operator confirmed (Fleet put `presence` on the claim) is run with `--commissioning
--person-at-switch`; the worker never declares a person itself. Every other task runs under the reviewed operating envelope
(D-911 `reviews` with a matching `task_sha256`); with no review the runner holds before any motion, which the worker reports
as REVIEW_REQUIRED.
"""
from __future__ import annotations

import time
from typing import Any

PRESENCE_MAX_AGE_S = 300.0   # Fleet takes a presence of at most 120 s at claim; the run starts right after
ZONE_BASIS = "predefined_side_and_top_target_zones"
TOP_ONLY_BASIS = "top_camera_only_target_zone"
# held by cell_envelope before any motion: no review, or a review that no longer fits the current task
REVIEW_REASONS = ("not_reviewed", "evidence_changed", "acceptance_not_met", "review_profile_mismatch", "evidence_unavailable",
                  "commissioning_requires_person")


def presence_ok(handoff: dict[str, Any], now: float | None = None) -> bool:
    """A claim-time presence {"operator", "at"} that is named and recent. Absent or stale: no supervised run."""
    p = handoff.get("presence")
    now = time.time() if now is None else now
    return (isinstance(p, dict) and isinstance(p.get("operator"), str) and bool(p["operator"].strip())
            and p["operator"] not in ("site-console",) and not p["operator"].startswith("development-")
            and isinstance(p.get("at"), (int, float)) and not isinstance(p.get("at"), bool) and -5.0 <= now - p["at"] <= PRESENCE_MAX_AGE_S)


def review_required(parsed: dict[str, Any]) -> bool:
    result = str(parsed.get("result") or "")
    return result.startswith("held: ") and result[len("held: "):] in REVIEW_REASONS


def zone_acceptance(zone: dict | None, handoff: dict[str, Any], dst: str) -> bool:
    """The zone record is verified, has the basis this cell may use, and is the task's own destination, tier and slot."""
    target = (zone or {}).get("target") if isinstance((zone or {}).get("target"), dict) else {}
    htier = handoff.get("tier")
    top_only = handoff.get("cell_id") == "cell_s" and (zone or {}).get("basis") == TOP_ONLY_BASIS
    roi = target.get("roi")
    slot_ok = (isinstance(roi, list) and len(roi) == 4 and all(type(v) in (int, float) for v in roi)) if top_only else (
        type(target.get("col")) is int and type(target.get("row")) is int)
    bound = target.get("site") == dst and type(htier) is int and target.get("tier") == htier and slot_ok
    return bool(zone and zone.get("verified") is True and (zone.get("basis") == ZONE_BASIS or top_only) and bound)
