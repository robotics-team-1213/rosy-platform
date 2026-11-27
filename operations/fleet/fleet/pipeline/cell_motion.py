"""Typed Fleet cell-task motions (D-1078 stage 2): a free-position pick and a push. Pure: errors are ValueError codes.

frame_seq and frame_sha256 are an audit record of the frame the requester chose, NOT a binding: the cell job API takes no frame
identity, it re-measures at execution and refuses when no measured blob lies at at_px.
This module only checks the request and limits who may admit it. The task still runs worker -> cell job API,
the one place that moves an arm: Gate, contact/torque guards, finger room, depth bounds, incident holds, stop proof.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from fleet.pipeline.cell_site_targets import list_canonical_sites

KEYS = {
    "free_pick": {"kind", "anchor_site", "at_px", "dst_site", "frame_seq", "frame_sha256", "object", "colour"},
    "push": {"kind", "site", "px", "dir", "mm", "frame_seq", "frame_sha256"},
}
#: free-pick fields that must be present (object and colour only narrow the choice).
REQUIRED = {"free_pick": ("anchor_site", "at_px", "dst_site", "frame_seq", "frame_sha256"),
            "push": ("site", "px", "dir", "mm", "frame_seq", "frame_sha256")}
#: task fields a motion replaces or contradicts: the motion names its own sites and runs one guarded pass.
CONFLICTS = ("preset", "tiers", "directive", "displaced_to", "depends_on", "tier_hint", "max_chunks")
_FILTER = re.compile(r"[a-z0-9_,-]{1,120}")
_SHA = re.compile(r"[0-9a-f]{64}")


def _bad(code: str = "INVALID_CELL_MOTION"):
    raise ValueError(code)  # the route turns a ValueError into a 422 with this code


def _int(v: Any, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        _bad()
    return v


def _num(v: Any, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        _bad()
    return v


def _pair(v: Any, lo: float, hi: float, as_int: bool) -> list:
    if not isinstance(v, list) or len(v) != 2:
        _bad()
    return [(_int if as_int else _num)(x, lo, hi) for x in v]


def known_sites(web_common: Path | None, legacy_sites: tuple[str, ...]) -> set[str]:
    sites = set(legacy_sites)
    for s in list_canonical_sites(web_common)["sites"]:
        sites.update(s[k] for k in ("site_id", "sim_site", "base_site") if s.get(k))
    return sites


def prepare_cell_motion(spec: dict[str, Any], *, cell_id: str, web_common: Path | None,
                        legacy_sites: tuple[str, ...]) -> tuple[dict[str, Any], dict | None]:
    """-> (spec whose src_site/dst_site come from the motion, the checked motion), or (spec, None) without one."""
    raw = spec.get("motion")
    if raw is None:
        return spec, None
    if not isinstance(raw, dict) or raw.get("kind") not in KEYS:
        _bad()
    kind = raw["kind"]
    if set(raw) - KEYS[kind] or any(k not in raw for k in REQUIRED[kind]):
        _bad()  # an unknown key (operator, reviewed_auto, metres) never passes; a missing one is not guessed
    if cell_id != "cell_ab":
        _bad("MOTION_CELL_NOT_SUPPORTED")  # the free pick is for the A/B arms; arm_s stays on fixed sites
    if any(spec.get(k) is not None for k in CONFLICTS) or spec.get("execution_mode") not in (None, "guarded_pick"):
        _bad("MOTION_CONFLICTS_WITH_TASK_FIELDS")
    m = {"kind": kind, "frame_seq": _int(raw["frame_seq"], 0, 2**53)}
    if not isinstance(raw["frame_sha256"], str) or not _SHA.fullmatch(raw["frame_sha256"]):
        _bad()
    m["frame_sha256"] = raw["frame_sha256"]
    if kind == "free_pick":
        m.update(anchor_site=raw["anchor_site"], dst_site=raw["dst_site"], at_px=_pair(raw["at_px"], 0, 1280, True))
        for k in ("object", "colour"):
            if k in raw:
                if not isinstance(raw[k], str) or not _FILTER.fullmatch(raw[k]):
                    _bad()
                m[k] = raw[k]
        src, dst = m["anchor_site"], m["dst_site"]
    else:
        d = _pair(raw["dir"], -100, 100, False)
        if d == [0, 0]:
            _bad()
        m.update(site=raw["site"], px=_pair(raw["px"], 0, 1280, True), dir=d, mm=_num(raw["mm"], 5, 20))
        src = dst = m["site"]  # a push stays on one site
    known = known_sites(web_common, legacy_sites)
    if not all(isinstance(s, str) and s in known for s in (src, dst)):
        _bad("UNKNOWN_CELL_SITE")
    if any(spec.get(k) not in (None, v) for k, v in (("src_site", src), ("dst_site", dst))):
        _bad("MOTION_SITE_CONFLICT")
    return {**spec, "src_site": src, "dst_site": dst}, m


def claim_refusal(task: dict[str, Any], body: dict[str, Any]) -> str | None:
    """Rollout gate: an old worker ignores `motion` and would pick from the anchor, so only a worker whose claim lists "motion" gets one."""
    caps = body.get("capabilities")
    return None if task.get("motion") is None or (isinstance(caps, list) and "motion" in caps) else "WORKER_LACKS_MOTION_CAPABILITY"


def restrict_motion_admission(motion: dict | None, status: str, meta: dict[str, Any], principal_role: str | None) -> tuple[str, dict[str, Any]]:
    """Owner decision 2026-11-27 (amends D-911 section 2): a free pick runs without per-task approval only when the D-1078
    switch is on AND a service principal created it without propose (approved_by autonomous_policy). Everyone else waits
    for a different named human on /admit: a creator never approves their own motion, and a push is never queued (it cannot run).
    """
    if motion is None or status != "QUEUED":
        return status, meta
    if motion["kind"] == "free_pick" and principal_role == "service" and meta.get("approved_by") == "autonomous_policy":
        return status, meta
    why = "HUMAN_APPROVAL_REQUIRED" if motion["kind"] == "free_pick" else "PUSH_NOT_EXECUTABLE"
    return "PROPOSED", {**{k: v for k, v in meta.items() if k != "approval_mode"}, "approved_by": None, "motion_admission": why}
