#!/usr/bin/env python3
"""Register a designated cell slot (e.g. ship-h1r0, tmp-a-1) in a cell-arm-{a,b}-stack.json 'sites' map.

register: add sites[<site>] with status 'unverified' (never overwrites; --replace keeps the old entry in history).
          Only designated slot names from cell-site-map are accepted; legacy names (pallet, belt, temp_plate_*, stand ...) never.
promote : records measured_z (a completed surface touch receipt) and/or measured_xy (a cell_post_eval report); status becomes
          'measured' only when both are present for the entry's current place, yaw and height.
cell_site_target.unmeasured_refusal stops every motion path (SITE_NOT_MEASURED) until then. The arm is never moved here.
Writes only the config path it is given, through cell_config_io (flock sidecar, mode kept, timestamped .bak files).
Order for a new slot: register, then Z (site_surface job -> surface-<site>.json, promote --z-evidence), then XY (post_eval job, promote
--post-eval). Z changes surface_z and makes any earlier XY report stale. Layers 1 and 2 open only after --tier-evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cell_config_io
from cell_site_target import designated_slot_arms, site_digest

SOURCES = ("cad", "depth", "probe")
ARMS = ("arm_a", "arm_b")
SITE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
TIER_SUFFIX = re.compile(r"-l[0-2]$")
POST_EVAL_SCHEMA = "rosy.omx-post-eval.v1"  # cell_post_eval.SCHEMA; not imported, that module pulls in camera code
MAX_ERROR_MM = 10.0  # shortcut: one global limit, upgrade when a per-site limit exists in the post_eval params
PLACE_TOL_M = 1e-3  # the evaluated point is the registered place
TOUCH_SPREAD_M = 0.0015
TIER_STEP_TOL_M = 0.0015
Z_MEAN_TOL_M = 0.00011  # cell_route_surface.contact_evidence uses the same bound
TOOL = "cell_site_register/2"


RegisterError = cell_config_io.ConfigError
atomic_write = cell_config_io.atomic_write  # re-exported


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def sha256_file(path) -> str:
    p = Path(path)
    if not p.is_file():
        raise RegisterError(f"file not found: {path}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _num(v, name) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise RegisterError(f"{name} must be a finite number")
    return float(v)


def _json_file(path, what: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegisterError(f"{what} unreadable: {exc}") from None
    if not isinstance(data, dict):
        raise RegisterError(f"{what} must be a JSON object")
    return data


def _report(text: str):
    """The report as a JSON file, or the last report object inside a cell-job-api log (the post_eval job prints it to stdout)."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    found, pos = None, 0
    for line in text.splitlines(keepends=True):
        if line.rstrip() == "{":
            try:
                obj, _ = json.JSONDecoder().raw_decode(text, pos)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and obj.get("schema") == POST_EVAL_SCHEMA:
                found = obj
        pos += len(line)
    return found


def _close(a, b, tol) -> bool:
    return isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b) == 2 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - w) <= tol for v, w in zip(a, b))


def read_post_eval(path, arm: str, site: str, entry: dict, max_error_mm: float = MAX_ERROR_MM) -> dict:
    """XY evidence: every row of the site passed at the registered place, report made for this arm and these exact values, after registration."""
    try:
        data = _report(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise RegisterError(f"post_eval report unreadable: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != POST_EVAL_SCHEMA:
        raise RegisterError(f"post_eval report schema must be {POST_EVAL_SCHEMA}")
    if data.get("arm") != arm:
        raise RegisterError(f"post_eval report is for arm {data.get('arm')!r}, not {arm!r}")
    if (data.get("site_digest") or {}).get(site) != site_digest(entry):
        raise RegisterError("post_eval report was not made for the registered place, yaw and surface_z of this site (re-run it)")
    try:
        at = datetime.fromisoformat(str(data.get("measured"))).timestamp()
    except ValueError:
        raise RegisterError("post_eval report has no measured time") from None
    if at < math.floor(entry["provenance"]["registered_epoch"]):  # the report time is cut to whole seconds
        raise RegisterError("post_eval report is older than the registration")
    rows = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("site") == site]
    if not rows:
        raise RegisterError(f"post_eval report has no row for site {site!r}")
    worst = 0.0
    for r in rows:
        if r.get("status") != "pass" or r.get("accepted") is not True:
            raise RegisterError(f"post_eval row for {site!r} is {r.get('status')!r}, not pass")
        if not _close(r.get("point_m"), entry["place"], PLACE_TOL_M):
            raise RegisterError(f"post_eval point {r.get('point_m')} is not the registered place {entry['place']}")
        worst = max(worst, _num(r.get("residual_mag_mm"), "residual_mag_mm"))
    if worst > max_error_mm:
        raise RegisterError(f"post_eval residual {worst} mm outside 0..{max_error_mm}")
    return {"error_mm": round(worst, 3), "rows": len(rows), "report_measured": data["measured"], "path": str(Path(path).resolve()),
            "sha256": sha256_file(path), "job_id": _job_id(path), "digest": site_digest(entry), "at": _now()}


def _job_id(path) -> str | None:
    p = Path(path).resolve()
    return p.stem if p.parent.name == "cell-job-api" else None  # cell_job_api names its log <job id>.log


def _read_touch(path, arm: str, name: str, entry: dict) -> dict:
    """A completed cell_surface touch receipt of this arm, name, place and yaw, made after registration."""
    d = _json_file(path, "surface receipt")
    b = d.get("contact_binding")
    if d.get("result") != "touched" or d.get("sets_surface_z") is not True or d.get("site") != name:
        raise RegisterError(f"surface receipt is not a completed touch of {name!r}")
    if not isinstance(b, dict) or b.get("arm") != arm or b.get("site") != name:
        raise RegisterError(f"surface receipt is not bound to arm {arm!r} and site {name!r}")
    if not (_close(d.get("xy"), entry["place"], PLACE_TOL_M) and _close(b.get("place"), entry["place"], PLACE_TOL_M)
            and isinstance(b.get("yaw_deg"), (int, float)) and abs(b["yaw_deg"] - entry["yaw_deg"]) <= 1e-6):
        raise RegisterError("surface receipt touched another place or yaw than the registered one")
    touches, z = d.get("touches_m"), d.get("surface_z")
    if not (isinstance(touches, list) and len(touches) >= 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in touches)):
        raise RegisterError("surface receipt needs at least two touches")
    z = _num(z, "surface_z")
    if abs(sum(touches) / len(touches) - z) > Z_MEAN_TOL_M or max(touches) - min(touches) > TOUCH_SPREAD_M or not -0.2 <= z <= 0.2:
        raise RegisterError("surface receipt touches disagree with surface_z")
    try:
        at = time.mktime(time.strptime(str(d.get("measured")), "%Y-%m-%d %H:%M"))  # the receipt keeps local minutes
    except ValueError:
        raise RegisterError("surface receipt has no measured time") from None
    if at < entry["provenance"]["registered_epoch"] - 60:
        raise RegisterError("surface receipt is older than the registration")
    return {"surface_z": z, "touches": len(touches), "receipt_measured": d["measured"], "path": str(Path(path).resolve()),
            "sha256": sha256_file(path), "job_id": _job_id(path), "at": _now()}


def read_z_evidence(path, arm: str, site: str, entry: dict) -> dict:
    """Z evidence: the touch receipt of the slot itself."""
    return {**_read_touch(path, arm, site, entry), "previous_surface_z": entry["surface_z"]}


def read_tier_evidence(path, arm: str, site: str, entry: dict) -> dict:
    """Tier step evidence: the touch receipt of <site>-l1 or -l2 (a box stood on the slot); its height over the measured
    surface_z, divided by the layer, must match the registered tier_step_m."""
    d = _json_file(path, "tier receipt")
    m = re.fullmatch(re.escape(site) + r"-l([12])", str(d.get("site")))
    if not m:
        raise RegisterError(f"tier receipt must be a touch of {site}-l1 or {site}-l2")
    layer = int(m.group(1))
    t = _read_touch(path, arm, d["site"], entry)
    step = (t["surface_z"] - entry["surface_z"]) / layer
    if abs(step - entry["tier_step_m"]) > TIER_STEP_TOL_M:
        raise RegisterError(f"tier receipt gives a step of {step:.4f} m, registered tier_step_m is {entry['tier_step_m']}; re-register with the measured step")
    return {"layer": layer, "step_m": round(step, 5), **t}


def _load(config) -> tuple[dict, str]:
    raw = Path(config).read_bytes()
    cfg = json.loads(raw.decode("utf-8"))
    if not isinstance(cfg.get("sites"), dict):
        raise RegisterError("config has no 'sites' object")
    return cfg, hashlib.sha256(raw).hexdigest()


def _check_site(cfg: dict, site: str, arm: str) -> None:
    if arm not in ARMS:
        raise RegisterError(f"arm must be one of {ARMS}")
    if not SITE.fullmatch(site) or TIER_SUFFIX.search(site):
        raise RegisterError("site must be a base name (no -l0/-l1/-l2 suffix)")
    if arm not in designated_slot_arms(site):
        raise RegisterError(f"{site!r} is not a designated slot of {arm} in cell-site-map (legacy and unknown names are refused)")
    for k in ("arm", "arm_id"):
        if cfg.get(k) not in (None, arm):
            raise RegisterError(f"config belongs to {cfg.get(k)!r}, not {arm!r}")


def register(config, arm, site, *, place, surface_z, yaw_deg, tier_step_m, map_from, source, evidence,
             operator=None, proposer=None, replace=False, dry_run=False) -> dict:
    with cell_config_io.locked(config):
        cfg, sha = _load(config)
        _check_site(cfg, site, arm)
        if len(place) != 2:
            raise RegisterError("place needs exactly x y")
        if source not in SOURCES:
            raise RegisterError(f"source must be one of {SOURCES}")
        if not isinstance(cfg["sites"].get(map_from), dict):
            raise RegisterError(f"map_from {map_from!r} is not a site in the config")
        entry = {"place": [_num(place[0], "place x"), _num(place[1], "place y")], "surface_z": _num(surface_z, "surface_z"),
                 "yaw_deg": _num(yaw_deg, "yaw_deg"), "tier_step_m": _num(tier_step_m, "tier_step_m"),
                 "map_from": map_from, "status": "unverified",
                 "provenance": {"source": source, "arm": arm, "registered_at": _now(), "registered_epoch": time.time(), "tool": TOOL,
                                "operator": operator, "proposer": proposer,
                                "evidence": {"path": str(Path(evidence).resolve()), "sha256": sha256_file(evidence)}},
                 "history": []}
        if not 0.01 <= entry["tier_step_m"] <= 0.1:
            raise RegisterError("tier_step_m outside 0.01..0.1 m")
        old = cfg["sites"].get(site)
        if old is not None:
            if not replace:
                raise RegisterError(f"site {site!r} already exists; use --replace (old value is kept in history)")
            if not (isinstance(old, dict) and str(old.get("provenance", {}).get("tool", "")).startswith("cell_site_register/")):
                raise RegisterError(f"site {site!r} was not registered by this tool; it is never replaced here")
            entry["history"] = [*(old.get("history") or []), {"replaced_at": _now(), "entry": {k: v for k, v in old.items() if k != "history"}}]
        cfg["sites"][site] = entry
        if not dry_run:
            cell_config_io.atomic_write(config, cell_config_io.dump(cfg), sha)
        return entry


def promote(config, arm, site, *, post_eval=None, z_evidence=None, tier_evidence=None, operator=None, proposer=None, dry_run=False) -> dict:
    if post_eval is None and z_evidence is None and tier_evidence is None:
        raise RegisterError("promote needs --z-evidence (Z), --post-eval (XY) and/or --tier-evidence (layers 1 and 2)")
    with cell_config_io.locked(config):
        cfg, sha = _load(config)
        _check_site(cfg, site, arm)
        entry = cfg["sites"].get(site)
        if not isinstance(entry, dict) or not str(entry.get("provenance", {}).get("tool", "")).startswith("cell_site_register/"):
            raise RegisterError(f"site {site!r} was not registered by this tool")
        if entry.get("status") == "measured" and (post_eval is not None or z_evidence is not None):
            raise RegisterError("already measured; re-register with --replace to change values")
        who = {"operator": operator, "proposer": proposer}
        if z_evidence is not None:
            z = read_z_evidence(z_evidence, arm, site, entry)
            entry["surface_z"] = z["surface_z"]  # the touched height replaces the registered one
            entry["measured_z"] = {**z, **who, "digest": site_digest(entry)}
        if tier_evidence is not None:
            entry["measured_tier_step"] = {**read_tier_evidence(tier_evidence, arm, site, entry), **who, "digest": site_digest(entry)}
        if post_eval is not None:
            entry["measured_xy"] = {**read_post_eval(post_eval, arm, site, entry), **who}
        for key in ("measured_xy", "measured_z", "measured_tier_step"):  # evidence about other values (a later height, say) no longer counts
            if key in entry and entry[key].get("digest") != site_digest(entry):
                del entry[key]
        entry["status"] = "measured" if "measured_xy" in entry and "measured_z" in entry else "unverified"
        if not dry_run:
            cell_config_io.atomic_write(config, cell_config_io.dump(cfg), sha)
        return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", required=True)
    common.add_argument("--arm", required=True, choices=ARMS)
    common.add_argument("--site", required=True)
    common.add_argument("--operator")
    common.add_argument("--proposer")
    common.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("register", parents=[common])
    r.add_argument("--place", nargs=2, type=float, required=True, metavar=("X", "Y"))
    r.add_argument("--surface-z", type=float, required=True)
    r.add_argument("--yaw-deg", type=float, required=True)
    r.add_argument("--tier-step-m", type=float, required=True)
    r.add_argument("--map-from", required=True)
    r.add_argument("--source", required=True, choices=SOURCES)
    r.add_argument("--evidence", required=True, help="file the values came from (its sha256 is recorded)")
    r.add_argument("--replace", action="store_true")
    p = sub.add_parser("promote", parents=[common])
    p.add_argument("--post-eval", help="XY: cell_post_eval report (JSON file or the post_eval job's log under cell-job-api/)")
    p.add_argument("--z-evidence", help="Z: the surface-<site>.json touch receipt of cell_surface")
    p.add_argument("--tier-evidence", help="layers 1 and 2: the touch receipt of <site>-l1 or <site>-l2")
    a = ap.parse_args(argv)
    who = {"operator": a.operator, "proposer": a.proposer, "dry_run": a.dry_run}
    try:
        if a.cmd == "register":
            e = register(a.config, a.arm, a.site, place=a.place, surface_z=a.surface_z, yaw_deg=a.yaw_deg, tier_step_m=a.tier_step_m,
                         map_from=a.map_from, source=a.source, evidence=a.evidence, replace=a.replace, **who)
        else:
            e = promote(a.config, a.arm, a.site, post_eval=a.post_eval, z_evidence=a.z_evidence, tier_evidence=a.tier_evidence, **who)
    except (RegisterError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"site": a.site, "status": e["status"], "measured_xy": "measured_xy" in e, "measured_z": "measured_z" in e, "measured_tier_step": "measured_tier_step" in e, "dry_run": a.dry_run}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
