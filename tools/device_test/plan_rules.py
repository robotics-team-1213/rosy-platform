"""D-512 plan loading: exact overlay key rules, waivers, stop rules; summary sanitizing."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

import yaml

MAX_LINEAR = 0.10            # m/s, rosy_default.yaml line_follow.max_linear (host default)
OVERLAY_PATH = "/var/lib/rosy/core/.rosy/rosy.yaml"   # rosy-core.service HOME (D-189 D3); the only one


def _num(lo, hi, lo_open=False, integer=False):
    def ok(v):
        if isinstance(v, bool) or not isinstance(v, int if integer else (int, float)):
            return False
        return (lo < v if lo_open else lo <= v) and v <= hi
    return ok, f"{'integer' if integer else 'number'} in {'(' if lo_open else '['}{lo}, {hi}]"


def _bool(v):
    return isinstance(v, bool)


# D-512 decision 4: exact keys, each with a value rule. Bridge values may only make the bridge
# more conservative than rosy_default.yaml (and stay inside LineFollowConfig._check_bridge):
# arm gates stricter, coast distance and slow scale smaller, odometry inflation and the
# LOST-clock margin larger. bridge_lookahead_m has no safer direction and is not allowed.
RULES = {
    "line_follow.bridge_enabled": (_bool, "bool"),
    "line_follow.bridge_arm_confidence": _num(0.5, 1.0),
    "line_follow.bridge_arm_frames": _num(3, 30, integer=True),
    "line_follow.bridge_arm_max_error": _num(0, 0.1, lo_open=True),
    "line_follow.bridge_arm_max_angular": _num(0, 0.08, lo_open=True),
    "line_follow.bridge_arm_max_curvature": _num(0, 4.0, lo_open=True),
    "line_follow.bridge_arm_curvature_tolerance": _num(0, 0.5, lo_open=True),
    "line_follow.bridge_coast_m": _num(0, 0.10, lo_open=True),
    # Also the re-arm distance (lane_bridge.py): smaller is not stricter, so only the default.
    "line_follow.bridge_slow_m": (lambda v: v == 0.25 and not isinstance(v, bool), "the default 0.25"),
    "line_follow.bridge_slow_scale": _num(0, 0.5, lo_open=True),
    "line_follow.bridge_distance_scale": _num(1.08, 2.0),
    "line_follow.bridge_time_margin_s": _num(0.5, 2.0),
    "line_follow.ir_guard_enabled": (lambda v: v is True, "true (the guard may only be turned on)"),
    "line_follow.recovery_local_enabled": (_bool, "bool"),
    "line_follow.cruise_speed": _num(0, MAX_LINEAR, lo_open=True),
    "line_follow.max_linear": _num(0, MAX_LINEAR, lo_open=True),
}
# Site declarations that waive a floor proof: allowed only with an accepted_risks entry.
WAIVERS = {
    "line_follow.bridge_site_no_dropoffs": (lambda v: v is True, "true"),
    "line_follow.junction_turn_site_accepted": (lambda v: v is True, "true"),
    "line_follow.site_floor_map_id": (lambda v: isinstance(v, str) and v != "site"
                                      and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", v) is not None, "map id"),
}


def _iso_date(v):
    if isinstance(v, dt.date):
        return True
    try:
        return bool(v) and dt.date.fromisoformat(str(v)) is not None
    except ValueError:
        return False


def check_overlay(flat, accepted_risks=()):
    accepted = {r.get("key"): r for r in accepted_risks or () if isinstance(r, dict)}
    for key, value in flat.items():
        if key in WAIVERS:
            risk = accepted.get(key) or {}
            if not (str(risk.get("accepted_by") or "").strip() and str(risk.get("reason") or "").strip()
                    and _iso_date(risk.get("date"))):
                raise SystemExit(f"plan overlay {key}: a site waiver needs accepted_risks "
                                 "{key, accepted_by, date, reason}")
            rule = WAIVERS[key]
        elif key in RULES:
            rule = RULES[key]
        else:
            raise SystemExit(f"plan overlay {key}: not an allowed test key (RULES in plan_rules.py)")
        if not rule[0](value):
            raise SystemExit(f"plan overlay {key}={value!r}: must be {rule[1]}")
    coast, slow = flat.get("line_follow.bridge_coast_m", 0.10), flat.get("line_follow.bridge_slow_m", 0.25)
    if coast > slow:   # LineFollowConfig refuses coast > slow at CORE start
        raise SystemExit(f"bridge_coast_m {coast} > bridge_slow_m {slow}")


def load_plan(path):
    plan = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not re.fullmatch(r"[a-z0-9-]+", str(plan.get("topic", ""))):
        raise SystemExit("plan needs topic: lower-case words joined by '-'")
    plan.setdefault("overlay", {})
    if plan.setdefault("overlay_path", OVERLAY_PATH) != OVERLAY_PATH:
        raise SystemExit(f"overlay_path must be {OVERLAY_PATH}")
    check_overlay(flatten(plan["overlay"]), plan.get("accepted_risks"))
    stop = plan.setdefault("stop", {})
    if not 0 < float(stop.get("duration_s", 0)) <= 600:
        raise SystemExit("stop.duration_s must be in (0, 600]")
    plan.setdefault("min_battery_percent", 40)
    plan.setdefault("verdict_max_age_s", 300)
    plan.setdefault("hold_s", 1.0)
    pol = plan["tether_policy"] = {"margin_m": 0.3, "max_turn_deg": 360, **(plan.get("tether_policy") or {})}
    # D-512 tether guard: only stricter than the user's 0.3 m / 360 deg; retrace unwinds to max_turn - 90
    if not (_num(0.2, 2.0)[0](pol["margin_m"]) and _num(90, 360, lo_open=True)[0](pol["max_turn_deg"])):
        raise SystemExit("tether_policy: margin_m in [0.2, 2.0], max_turn_deg in (90, 360]")
    if not 0 < float(plan["hold_s"]) <= 1.0:
        raise SystemExit("hold_s must be in (0, 1] so CORE's deadman stops a stalled loop within 1 s")
    return plan


# Known ids pass unchanged: sha256 digests, recording ids (20261008T120000Z-...), release ids.
KEEP = re.compile(r"sha256:[0-9a-f]{64}|\d{8}T\d{6}Z[-\w]{1,64}|\d{4}\.\d{2}\.\d{2}-\d{3}")


def sanitize_text(text):
    """Free text bound for the public repo: no addresses, URLs, .local hosts or token-like strings."""
    if KEEP.fullmatch(text):
        return text
    text = re.sub(r"https?://[^\s\"']+", "<url>", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<ip>", text)
    text = re.sub(r"\b[\w-]+\.local\b", "<host>.local", text)
    text = re.sub(r"(?i)bearer\s+[\"']?[^\s\"']+", "Bearer <redacted>", text)
    return re.sub(r"\b(?=[\w-]*[A-Z])(?=[\w-]*[a-z])(?=[\w-]*\d)[\w-]{24,}\b",
                  lambda m: m.group(0) if KEEP.fullmatch(m.group(0)) else "<redacted>", text)


def sanitize(value):
    """Walk a JSON-able structure and sanitize string keys and values (numbers stay)."""
    if isinstance(value, dict):
        return {sanitize_text(k) if isinstance(k, str) else k: sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return sanitize_text(value) if isinstance(value, str) else value


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out.get(k) or {}, v) if isinstance(v, dict) else v
    return out


VERDICT_KEYS = ("robot_at_start", "robot_seen_is_target", "path_clear", "cable_seen",
                "cable_attached", "cable_in_path_or_wheels")


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_verdict(path, max_age_s, now, pose):
    """The agent's visual verdict on the preflight frames (D-512 decision 3). Fails closed:
    ValueError for anything not shown to be safe. Returns the verdict dict."""
    path = Path(path)
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"camera verdict unreadable: {exc}") from exc
    missing = [k for k in VERDICT_KEYS if not isinstance(v.get(k), bool)]
    if missing:
        raise ValueError(f"camera verdict: {missing} must be true/false")
    if not str(v.get("judged_by") or "").strip():
        raise ValueError("camera verdict: judged_by is empty")
    frames = v.get("frames") or {}
    if not any(n.endswith("_overhead.jpg") for n in frames) or not any(n.endswith("_front.jpg") for n in frames):
        raise ValueError("camera verdict: needs an overhead and a front frame")
    for name, digest in frames.items():
        f = path.parent / Path(name).name
        if not f.is_file() or sha(f) != digest:
            raise ValueError(f"camera verdict: frame {name} missing or changed since it was judged")
    age = now - float(v.get("captured_at") or 0)
    if not 0 <= age <= max_age_s:
        raise ValueError(f"camera verdict is {age:.0f} s old (max {max_age_s} s)")
    was = v.get("pose_at_capture")
    if not (isinstance(pose, dict) and isinstance(was, dict)):
        raise ValueError("pose unknown: cannot show the robot has not moved since the judged frames")
    if math.hypot(pose["x"] - was["x"], pose["y"] - was["y"]) > 0.05:
        raise ValueError("robot moved since the judged frames; run --preflight-only again")
    if v["cable_in_path_or_wheels"] and v.get("tether") is None:   # own charging tether: user 2026-10-08
        raise ValueError("camera verdict: cable in the planned path or the wheels and no tether declared")
    bad = [k for k in ("robot_at_start", "robot_seen_is_target", "path_clear") if not v[k]]
    if bad:
        raise ValueError(f"camera verdict: {bad} false")
    return v
