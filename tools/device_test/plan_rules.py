"""D-512 plan loading: overlay allowlist, speed cap, stop rules; summary text sanitizing."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

MAX_LINEAR = 0.10            # m/s, rosy_default.yaml line_follow.max_linear (host default)
OVERLAY_PATH = "/var/lib/rosy/core/.rosy/rosy.yaml"   # rosy-core.service HOME (D-189 D3)
SAFE = re.compile(r"^[A-Za-z0-9_./-]+$")
# D-512 decision 4: a plan may turn test features on, never a safety function off.
DENY = re.compile(r"(obstacle|body_|teleop|watchdog|hold|sensor_adapter|safety|estop|limit|stop_)")
ALLOW = re.compile(r"line_follow\.(bridge_[a-z_]+|ir_guard_enabled|recovery_local_enabled|cruise_speed|"
                   r"max_linear|site_floor_map_id|junction_turn_site_accepted)")
SPEED_KEYS = ("line_follow.cruise_speed", "line_follow.max_linear")


def sanitize(text):
    """Free text bound for the public repo: no addresses, URLs, .local hosts or token-like strings."""
    text = re.sub(r"https?://[^\s\"']+", "<url>", str(text))
    text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<ip>", text)
    text = re.sub(r"\b[\w-]+\.local\b", "<host>.local", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    return re.sub(r"(?<!sha256:)\b(?=[\w-]*[A-Z])(?=[\w-]*[a-z])(?=[\w-]*\d)[\w-]{24,}\b", "<redacted>", text)


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


def check_overlay(flat):
    for key, value in flat.items():
        if DENY.search(key):
            raise SystemExit(f"plan overlay {key}: weakens or bypasses a safety function (D-512 decision 4)")
        if not ALLOW.fullmatch(key):
            raise SystemExit(f"plan overlay {key}: not an allowed test key (see ALLOW in run.py)")
        if key == "line_follow.ir_guard_enabled" and value is not True:
            raise SystemExit("plan overlay may only turn the IR guard on")
        if key in SPEED_KEYS and not (isinstance(value, (int, float)) and 0 < value <= MAX_LINEAR):
            raise SystemExit(f"{key} {value} outside (0, {MAX_LINEAR}] m/s")


def load_plan(path):
    plan = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not re.fullmatch(r"[a-z0-9-]+", str(plan.get("topic", ""))):
        raise SystemExit("plan needs topic: lower-case words joined by '-'")
    plan.setdefault("overlay", {})
    plan.setdefault("overlay_path", OVERLAY_PATH)
    if not SAFE.match(plan["overlay_path"]):
        raise SystemExit("overlay_path has characters a remote shell would interpret")
    check_overlay(flatten(plan["overlay"]))
    stop = plan.setdefault("stop", {})
    if not 0 < float(stop.get("duration_s", 0)) <= 600:
        raise SystemExit("stop.duration_s must be in (0, 600]")
    plan.setdefault("min_battery_percent", 40)
    plan.setdefault("verdict_max_age_s", 300)
    plan.setdefault("hold_s", 1.0)
    if not 0 < float(plan["hold_s"]) <= 1.0:
        raise SystemExit("hold_s must be in (0, 1] so CORE's deadman stops a stalled loop within 1 s")
    return plan
