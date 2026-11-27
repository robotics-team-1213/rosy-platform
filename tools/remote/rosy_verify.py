"""verify_after: the camera decides, not the job's exit code and not the model.

Compares the observation pack taken BEFORE a step with a fresh one AFTER it and returns a typed verdict:
VERIFIED, UNOBSERVABLE, ARM_NOT_SAFE, COLLATERAL, MISPLACED, NOT_MOVED, INCONCLUSIVE. Only VERIFIED is success.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from . import rosy_observe as obs
except ImportError:  # run as a script from tools/remote
    import rosy_observe as obs

MOVE_TOL_MM = 10.0   # a blob that moved less than this is the same blob (map error 5-13 mm, repeat spread 2 mm)
PLACE_TOL_MM = 20.0  # arrival tolerance around the planned place point
PUSH_MM = (3.0, 30.0)  # a push is 5..20 mm; allow slack either side. Below 3 mm the blob is the same one (repeat spread), so a 5 mm push is seen
NEXT = {
    "VERIFIED": [], "UNVERIFIABLE": ["re_observe", "ask_human"], "UNOBSERVABLE": ["re_observe", "ask_human"], "ARM_NOT_SAFE": ["ask_human"],
    "COLLATERAL": ["ask_human"], "MISPLACED": ["ask_human"], "INCONCLUSIVE": ["re_observe", "ask_human"],
    "NOT_MOVED": ["re_observe", "alternate_target", "push_first", "ask_human"],
}


def _d(a: list[float] | None, b: list[float] | None) -> float:
    return math.dist(a, b) if a and b else math.inf


def _at(pack: dict[str, Any], site: str) -> list[dict[str, Any]]:
    return [c for c in pack.get("candidates") or [] if c["site"] == site]


def _dest_site(pack: dict[str, Any], dest: str | None) -> str | None:
    regs = [r["site"] for r in pack.get("regions") or [] if r.get("role") == "dest"]
    return dest if dest in regs else (regs[0] if regs else None)


def _observed(pack: dict[str, Any], site: str | None) -> bool:  # a site whose dry run errored is unknown, not empty
    return any(r["site"] == site and r.get("result") != "error" for r in pack.get("runs") or [])


def _fresh(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    for name, p in (("before", before), ("after", after)):
        if p.get("observation_id") != obs.pack_id(p):
            return f"{name} pack does not match its observation_id"
    if not after.get("observable"):
        return f"after is unobservable: {after.get('reason')}"
    if not before.get("observable"):
        return "before is unobservable"
    if after.get("arm") != before.get("arm"):
        return "after is for another arm"
    if float(after.get("observed_at") or 0) <= float(before.get("observed_at") or 0):
        return "after is not newer than before"
    return None


def _arm_state(after: dict[str, Any]) -> str | None:
    r = after.get("readiness") or {}
    if not r.get("ok"):
        return "readiness unknown"
    bad = [k for k in ("incident_held", "human_hold_latched", "fault") if r.get(k)]
    if bad or r.get("folded") is not True:
        return f"folded={r.get('folded')} {bad}"
    return None


def verify_after(before: dict[str, Any], after: dict[str, Any], step: dict[str, Any], *, job_exit: int | None = None,
                 move_tol_mm: float = MOVE_TOL_MM, place_tol_mm: float = PLACE_TOL_MM) -> dict[str, Any]:
    """Typed verdict for one pick/free_pick/push step. job_exit is echoed and never used."""
    def out(verdict: str, checks: dict[str, Any]) -> dict[str, Any]:
        return {"verdict": verdict, "ok": verdict == "VERIFIED", "checks": checks, "next": NEXT[verdict],
                "before": before.get("observation_id"), "after": after.get("observation_id"), "job_exit_ignored": job_exit}

    if why := _fresh(before, after):
        return out("UNOBSERVABLE", {"why": why})
    checks: dict[str, Any] = {}
    if why := _arm_state(after):
        return out("ARM_NOT_SAFE", {"arm_state": why})
    verb, tid = step.get("verb"), step.get("target")
    moved = next((c for c in before["candidates"] if c["id"] == tid and c.get("centre_mm")), None) if isinstance(tid, str) else None
    if moved is None:  # free_pick pixel or retier site: the pack holds no measured blob to follow, so the camera cannot say what moved
        return out("UNVERIFIABLE", {"why": "target is not a measured candidate of the before pack"})
    site = moved["site"]
    if not (_observed(before, site) and _observed(after, site)):
        return out("INCONCLUSIVE", {"source": {"site": site, "why": "source not observed before and after (dry run errored)"}})
    new = _at(after, site)
    tol = PUSH_MM[0] if verb == "push" else move_tol_mm  # a push shifts a blob by as little as 5 mm: that must not read as "still there"
    dist = [(c, _d(c["centre_mm"], moved["centre_mm"])) for c in new]
    near = [c for c, d in dist if d <= tol]
    shifted = [c for c, d in dist if PUSH_MM[0] < d <= PUSH_MM[1]]
    cleared = not near
    checks["source"] = {"site": site, "cleared": cleared, "still_there": len(near)}
    rest = [c for c in before["candidates"] if c is not moved]  # the moved blob itself is not "another box"
    left = [c["id"] for c in rest if not any(a["site"] == c["site"] and _d(a["centre_mm"], c["centre_mm"]) <= move_tol_mm for a in after["candidates"])]
    checks["others_unmoved"] = {"ok": not left, "moved_or_gone": left}
    if left:
        return out("COLLATERAL", checks)
    if verb == "push":
        checks["pushed"] = {"ok": bool(shifted) and not near, "shifted_blobs": len(shifted)}
        return out("VERIFIED" if checks["pushed"]["ok"] else "NOT_MOVED", checks)
    if not cleared:
        return out("NOT_MOVED", checks)
    dsite = _dest_site(after, step.get("dest"))
    if not (_observed(before, dsite) and _observed(after, dsite)):
        checks["arrived"] = {"ok": None, "why": "destination not observed before and after"}
        return out("INCONCLUSIVE", checks)
    want = moved.get("matched_id")
    old_dest = _at(before, dsite)
    fresh = [c for c in _at(after, dsite) if (want is None or c.get("matched_id") == want)
             and not any(_d(c["centre_mm"], o["centre_mm"]) <= move_tol_mm for o in old_dest)]
    place = moved.get("place_mm")
    best = min((_d(c["centre_mm"], place) for c in fresh), default=math.inf) if place else None
    ok = bool(fresh) and (best is None or best <= place_tol_mm)
    checks["arrived"] = {"ok": ok, "site": dsite, "new_blobs": len(fresh), "position_checked": place is not None,
                         "distance_to_plan_mm": None if best in (None, math.inf) else round(best, 1)}
    return out("VERIFIED" if ok else "MISPLACED", checks)
