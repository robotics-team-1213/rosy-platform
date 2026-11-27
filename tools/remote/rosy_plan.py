"""Closed plan schema and the validator that checks one step against the observation pack it cites.

A model fills ONE step: {verb, arm, target, dest, reason}. It never gives metres, an operator, a proposer, reviewed_auto or
person_at_switch: those keys are refused by name. A target is a candidate id of the pack, a site (a retier site the pack
suggested), or {anchor, at_px} for free_pick/push. Deterministic checks only; this never replaces the cell's guards.
"""
from __future__ import annotations

import json
import re
from typing import Any

try:
    from . import rosy_observe as obs
except ImportError:  # run as a script from tools/remote
    import rosy_observe as obs

VERBS = ("pick", "free_pick", "push", "idle", "ask_human")
MOTION = frozenset({"pick", "free_pick", "push"})
MAX_PLAN_AGE_S = 30.0  # lens C: a plan older than this re-observes
_SITE = r"[a-z0-9_][a-z0-9_.-]{0,62}"
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["observation_id", "step"],
    "properties": {
        "observation_id": {"type": "string"},
        "step": {
            "type": "object", "additionalProperties": False, "required": ["verb", "arm", "reason"],
            "properties": {
                "verb": {"enum": list(VERBS)}, "arm": {"enum": ["arm_a", "arm_b", "arm_s"]},
                "target": {"oneOf": [
                    {"type": "string", "pattern": r"^c[0-9]+$"}, {"type": "string", "pattern": f"^{_SITE}$"},
                    {"type": "object", "additionalProperties": False, "required": ["anchor", "at_px"],
                     "properties": {"anchor": {"type": "string", "pattern": f"^{_SITE}$"},
                                    "at_px": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 2, "maxItems": 2}}}]},
                "dest": {"type": "string", "pattern": f"^{_SITE}$"},
                "reason": {"type": "string", "maxLength": 200},
            },
        },
    },
}
_FORBIDDEN = re.compile(r"^(x|y|z|xyz|yaw|yaw_deg|metres|meters|mm|operator|proposer|reviewed_auto|person_at_switch|approval|approved_by|.*_m|.*_mm|pick_.*|place_.*)$")


def _e(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _check_shape(plan: Any, errs: list[dict[str, str]]) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        errs.append(_e("BAD_PLAN", "plan must be a JSON object"))
        return None
    for k in plan:
        if k not in ("observation_id", "step"):
            errs.append(_e("FORBIDDEN_FIELD" if _FORBIDDEN.match(str(k)) else "UNKNOWN_FIELD", k))
    step = plan.get("step")
    if not isinstance(plan.get("observation_id"), str) or not isinstance(step, dict):
        errs.append(_e("BAD_PLAN", "observation_id (string) and step (object) are required"))
        return None
    for k in step:
        if k not in PLAN_SCHEMA["properties"]["step"]["properties"]:
            errs.append(_e("FORBIDDEN_FIELD" if _FORBIDDEN.match(str(k)) else "UNKNOWN_FIELD", f"step.{k}"))
    if step.get("verb") not in VERBS:
        errs.append(_e("BAD_VERB", f"verb must be one of {list(VERBS)}"))
    if not isinstance(step.get("reason"), str) or not step["reason"].strip() or len(step["reason"]) > 200:
        errs.append(_e("BAD_REASON", "reason is a non-empty string of at most 200 characters"))
    t = step.get("target")
    if isinstance(t, dict):
        ok = set(t) == {"anchor", "at_px"} and isinstance(t["anchor"], str) and isinstance(t["at_px"], list) and len(t["at_px"]) == 2 \
            and all(type(v) is int and v >= 0 for v in t["at_px"])
        if not ok:
            errs.append(_e("BAD_TARGET", "target object is exactly {anchor: site, at_px: [u, v]} in whole pixels, no metres"))
    elif t is not None and not (isinstance(t, str) and re.fullmatch(_SITE, t)):
        errs.append(_e("BAD_TARGET", "target is a candidate id, a site name or {anchor, at_px}"))
    d = step.get("dest")
    if d is not None and not (isinstance(d, str) and re.fullmatch(_SITE, d)):
        errs.append(_e("BAD_DEST", "dest is a site name"))
    return step


def _sites(pack: dict[str, Any]) -> set[str]:
    base = {r["site"] for r in pack.get("regions") or []}
    return base | {f"{s}-l{n}" for s in base for n in range(3)}


def _check_motion(step: dict[str, Any], pack: dict[str, Any], errs: list[dict[str, str]]) -> None:
    verb, t, d = step["verb"], step.get("target"), step.get("dest")
    cands = {c["id"]: c for c in pack.get("candidates") or []}
    rd = pack.get("readiness") or {}
    if not rd.get("ok") or rd.get("incident_held") or rd.get("human_hold_latched") or rd.get("fault") or rd.get("active_job_id") or rd.get("dirty"):
        errs.append(_e("ARM_NOT_READY", "readiness is unknown, held, faulted, dirty or busy: only idle or ask_human"))
    if not (pack.get("live_verbs") or {}).get(verb):
        errs.append(_e("VERB_NOT_LIVE", f"the live cell API does not accept {verb} now"))
    if verb == "push":
        if d is not None:
            errs.append(_e("BAD_DEST", "push has no dest"))
    elif d not in (pack.get("dests") or []):
        errs.append(_e("UNKNOWN_DEST", f"dest {d!r} is not one of {pack.get('dests')}"))
    if t is None:
        errs.append(_e("MISSING_TARGET", f"{verb} needs a target"))
    elif isinstance(t, dict):
        reg = next((r for r in pack.get("regions") or [] if r["site"] == t["anchor"] and r.get("role") == "source"), None)
        if verb == "pick":
            errs.append(_e("BAD_TARGET", "pick takes a candidate id or a retier site, not a pixel"))
        elif reg is None:
            errs.append(_e("UNKNOWN_SITE", f"anchor {t['anchor']!r} is not a source site of this arm"))
        else:
            u, v = t["at_px"]
            x0, y0, x1, y1 = reg["roi"]
            if reg.get("trusted") is False or not (x0 <= u <= x1 and y0 <= v <= y1):
                errs.append(_e("PIXEL_NOT_IN_SITE", f"at_px {t['at_px']} is outside the trusted region of {t['anchor']}"))
            if verb == "free_pick" and obs.arm_cfg(pack["arm"]).get("free_pick") is False:
                errs.append(_e("VERB_NOT_ALLOWED_FOR_ARM", f"{pack['arm']} has no depth camera: no free_pick"))
    elif t in cands:
        if verb not in cands[t]["suggestions"]:
            errs.append(_e("TARGET_REFUSED", f"{t} allows {cands[t]['suggestions']}, not {verb}"))
    elif verb == "pick" and any(f"retier({t})" in c["suggestions"] for c in cands.values()):
        pass
    elif re.fullmatch(r"c[0-9]+", str(t)):
        errs.append(_e("TARGET_NOT_IN_PACK", f"candidate {t} is not in observation {pack.get('observation_id')}"))
    elif t in _sites(pack):
        errs.append(_e("SITE_NOT_SUGGESTED", f"site {t} was not suggested by the pack (a retier site is)"))
    else:
        errs.append(_e("UNKNOWN_SITE", f"{t!r} is not a site of this arm"))


def validate_plan(plan: Any, pack: dict[str, Any], *, now: float | None = None, max_age_s: float = MAX_PLAN_AGE_S,
                  history: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ()) -> dict[str, Any]:
    """{ok, errors:[{code, detail}], step, needs_human_approval}. history: [{step, verdict}] of this episode."""
    errs: list[dict[str, str]] = []
    step = _check_shape(plan, errs)
    if step is None or errs:
        return {"ok": False, "errors": errs, "step": None, "needs_human_approval": False}
    if plan["observation_id"] != pack.get("observation_id"):
        errs.append(_e("OBSERVATION_MISMATCH", f"plan cites {plan['observation_id']}, pack is {pack.get('observation_id')}"))
    if now is not None and now - float(pack.get("observed_at") or 0) > max_age_s:
        errs.append(_e("OBSERVATION_STALE", f"observation older than {max_age_s} s: observe again"))
    if step["arm"] != pack.get("arm"):
        errs.append(_e("ARM_MISMATCH", f"step arm {step['arm']} but the pack is for {pack.get('arm')}"))
    verb = step["verb"]
    if verb in MOTION:
        if not pack.get("observable"):
            errs.append(_e("UNOBSERVABLE", f"{pack.get('reason')}: only idle or ask_human"))
        else:
            _check_motion(step, pack, errs)
    elif step.get("target") is not None or step.get("dest") is not None:
        errs.append(_e("BAD_TARGET", f"{verb} takes no target or dest"))
    canon = json.dumps(step, sort_keys=True)
    if any(json.dumps(h.get("step"), sort_keys=True) == canon and h.get("verdict") != "VERIFIED" for h in history):
        errs.append(_e("REPEAT_AFTER_FAILURE", "the same step already failed in this episode: re-observe and choose another"))
    return {"ok": not errs, "errors": errs, "step": step, "needs_human_approval": verb == "push"}
