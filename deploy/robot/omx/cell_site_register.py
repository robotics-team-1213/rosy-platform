#!/usr/bin/env python3
"""Register a designated cell slot (e.g. ship-h1r0, tmp-a-1) in a cell-arm-{a,b}-stack.json 'sites' map.

register: add sites[<site>] with status 'unverified' (never overwrites; --replace keeps the old entry in history)
promote : unverified -> 'measured', only from a passing cell_post_eval report (rosy.omx-post-eval.v1) for that site
cell_site_target.calibration_refusal refuses an unverified slot (SITE_NOT_MEASURED), so register alone never opens the arm.
Does not move the arm. Writes only the config path it is given (a symlink is followed, so the link survives).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

SOURCES = ("cad", "depth", "probe")
ARMS = ("arm_a", "arm_b")
SITE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
TIER_SUFFIX = re.compile(r"-l[0-2]$")
POST_EVAL_SCHEMA = "rosy.omx-post-eval.v1"  # cell_post_eval.SCHEMA; not imported, that module pulls in camera code
MAX_ERROR_MM = 10.0  # shortcut: one global limit, upgrade when a per-site limit exists in the post_eval params
PLACE_MATCH_M = 0.010  # the evaluated point must be the registered place
TOOL = "cell_site_register/1"


class RegisterError(ValueError):
    pass


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


def _report(text: str):
    """The report as a JSON file, or the last report object inside a cell-job-api log (the post_eval job prints it to stdout)."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    found = None
    pos = 0
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


def read_post_eval(path, site: str, place, max_error_mm: float = MAX_ERROR_MM) -> dict:
    """Checked summary of a cell_post_eval report: every row of the site passed, at the registered place, within max_error_mm."""
    try:
        data = _report(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise RegisterError(f"post_eval report unreadable: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != POST_EVAL_SCHEMA:
        raise RegisterError(f"post_eval report schema must be {POST_EVAL_SCHEMA}")
    rows = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("site") == site]
    if not rows:
        raise RegisterError(f"post_eval report has no row for site {site!r}")
    worst = 0.0
    for r in rows:
        if r.get("status") != "pass" or r.get("accepted") is not True:
            raise RegisterError(f"post_eval row for {site!r} is {r.get('status')!r}, not pass")
        pt = r.get("point_m")
        if not (isinstance(pt, list) and len(pt) == 2) or math.dist([_num(v, "point_m") for v in pt], place) > PLACE_MATCH_M:
            raise RegisterError(f"post_eval point {pt} is not the registered place {list(place)}")
        worst = max(worst, _num(r.get("residual_mag_mm"), "residual_mag_mm"))
    if worst > max_error_mm:
        raise RegisterError(f"post_eval residual {worst} mm outside 0..{max_error_mm}")
    return {"verdict": "pass", "error_mm": round(worst, 3), "rows": len(rows), "measured": data.get("measured"),
            "path": str(Path(path).resolve()), "sha256": sha256_file(path), "at": _now()}


def atomic_write(path, text: str) -> None:
    """Same-folder temp file, fsync, os.replace; the previous file is copied to <path>.bak first. A symlink is resolved first."""
    path = Path(path).resolve()
    shutil.copy2(path, str(path) + ".bak")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    if hasattr(os, "O_DIRECTORY"):  # POSIX: persist the rename too
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _load(config) -> dict:
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    if not isinstance(cfg.get("sites"), dict):
        raise RegisterError("config has no 'sites' object")
    return cfg


def _check_site(cfg: dict, site: str, arm: str) -> None:
    if arm not in ARMS:
        raise RegisterError(f"arm must be one of {ARMS}")
    if not SITE.fullmatch(site) or TIER_SUFFIX.search(site):
        raise RegisterError("site must be a base name (no -l0/-l1/-l2 suffix)")
    for k in ("arm", "arm_id"):
        if cfg.get(k) not in (None, arm):
            raise RegisterError(f"config belongs to {cfg.get(k)!r}, not {arm!r}")


def _dump(cfg: dict) -> str:
    return json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"  # shortcut: re-indents the file to 2 spaces


def register(config, arm, site, *, place, surface_z, yaw_deg, tier_step_m, map_from, source, evidence,
             operator=None, proposer=None, replace=False, dry_run=False) -> dict:
    cfg = _load(config)
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
             "provenance": {"source": source, "arm": arm, "registered_at": _now(), "tool": TOOL, "operator": operator, "proposer": proposer,
                            "evidence": {"path": str(Path(evidence).resolve()), "sha256": sha256_file(evidence)}},
             "history": []}
    if not 0.01 <= entry["tier_step_m"] <= 0.1:
        raise RegisterError("tier_step_m outside 0.01..0.1 m")
    old = cfg["sites"].get(site)
    if old is not None:
        if not replace:
            raise RegisterError(f"site {site!r} already exists; use --replace (old value is kept in history)")
        entry["history"] = [*(old.get("history") or []), {"replaced_at": _now(), "entry": {k: v for k, v in old.items() if k != "history"}}]
    cfg["sites"][site] = entry
    if not dry_run:
        atomic_write(config, _dump(cfg))
    return entry


def promote(config, arm, site, post_eval_path, *, operator=None, proposer=None, dry_run=False) -> dict:
    cfg = _load(config)
    _check_site(cfg, site, arm)
    entry = cfg["sites"].get(site)
    if not isinstance(entry, dict) or entry.get("provenance", {}).get("tool") != TOOL:
        raise RegisterError(f"site {site!r} was not registered by this tool")
    if entry.get("status") == "measured":
        raise RegisterError("already measured; re-register with --replace to change values")
    entry["provenance"]["post_eval"] = {**read_post_eval(post_eval_path, site, entry["place"]), "operator": operator, "proposer": proposer}
    entry["status"] = "measured"
    if not dry_run:
        atomic_write(config, _dump(cfg))
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
    p.add_argument("--post-eval", required=True, help="cell_post_eval report: a JSON file or the post_eval job's log under cell-job-api/")
    a = ap.parse_args(argv)
    who = {"operator": a.operator, "proposer": a.proposer, "dry_run": a.dry_run}
    try:
        if a.cmd == "register":
            e = register(a.config, a.arm, a.site, place=a.place, surface_z=a.surface_z, yaw_deg=a.yaw_deg, tier_step_m=a.tier_step_m,
                         map_from=a.map_from, source=a.source, evidence=a.evidence, replace=a.replace, **who)
        else:
            e = promote(a.config, a.arm, a.site, a.post_eval, **who)
    except (RegisterError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"site": a.site, "status": e["status"], "dry_run": a.dry_run}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
