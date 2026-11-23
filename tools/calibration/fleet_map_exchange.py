#!/usr/bin/env python3
"""Operator CLI for bidirectional Fleet <-> CORE master-map exchange (2026-11-23).

Subcommands:
  pull       Fetch GET /api/fleet/robots/{robot}/map/bundle -> <out>/<stem>.{pgm,yaml,meta.json}
  upload     Verify sealed yaw=0 bundle via map_bundle and PUT /api/fleet/site-map/master-grid
  push       POST /api/fleet/robots/{robot}/master-map/push (stage or stage+activate)
  verify-loc Poll GET /api/fleet/state until every robot is LOCALIZED on the master grid_id
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slam_map_align as sma  # noqa: E402


class ExchangeError(RuntimeError):
    """Operator-facing exchange failure (network, HTTP, or verification)."""


class FleetClient:
    """Thin urllib client for Fleet master-map endpoints with optional CA bundle."""

    def __init__(self, base_url: str, *, token: str = "", ca: Optional[Path] = None, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = float(timeout)
        self._ctx = ssl.create_default_context(cafile=str(ca)) if ca is not None else None

    def request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise ExchangeError(f"{method} {path} failed ({exc.code}): {err_body}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ExchangeError(f"{method} {path} transport error: {exc}") from exc
        parsed = json.loads(raw) if raw.strip() else {}
        if not isinstance(parsed, dict):
            raise ExchangeError(f"{method} {path} returned non-object JSON")
        return parsed


def cmd_pull(client: FleetClient, args: argparse.Namespace) -> dict[str, Any]:
    robot_id = args.robot
    bundle = client.request("GET", f"/api/fleet/robots/{robot_id}/map/bundle")
    pgm = base64.b64decode(bundle["pgm_base64"], validate=True)
    if hashlib.sha256(pgm).hexdigest() != bundle["sha256"]:
        raise ExchangeError("downloaded PGM sha256 does not match bundle sha256")
    stem = args.name or f"robot_{re.sub(r'[^A-Za-z0-9._-]', '_', robot_id)}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    pgm_path = args.out_dir / f"{stem}.pgm"
    yaml_path = args.out_dir / f"{stem}.yaml"
    meta_path = args.out_dir / f"{stem}.meta.json"
    pgm_path.write_bytes(pgm)
    yaml_doc = {**bundle["yaml"], "image": pgm_path.name}
    yaml_path.write_text(yaml.safe_dump(yaml_doc, sort_keys=False), encoding="utf-8", newline="\n")
    meta_doc = {
        "robot_id": bundle.get("robot_id", robot_id),
        "map_id": bundle.get("map_id"),
        "grid_id": bundle["grid_id"],
        "sha256": bundle["sha256"],
        "width": bundle["width"],
        "height": bundle["height"],
        "resolution": bundle["resolution"],
        "origin": bundle["origin"],
    }
    meta_path.write_text(json.dumps(meta_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {
        "robot_id": robot_id,
        "grid_id": bundle["grid_id"],
        "sha256": bundle["sha256"],
        "yaml": str(yaml_path),
        "pgm": str(pgm_path),
    }


def cmd_upload(client: FleetClient, args: argparse.Namespace) -> dict[str, Any]:
    sealed_yaml: Path = args.sealed_yaml
    mb = sma.load_map_bundle_module()
    problems = mb.verify_bundle(sealed_yaml, require_zero_yaw=True, require_manifest=True)
    if problems:
        raise ExchangeError("bundle failed verification: " + "; ".join(problems))
    meta = yaml.safe_load(sealed_yaml.read_text(encoding="utf-8"))
    manifest = json.loads((sealed_yaml.parent / "manifest.json").read_text(encoding="utf-8"))
    pgm_bytes = (sealed_yaml.parent / meta["image"]).read_bytes()
    sha256 = hashlib.sha256(pgm_bytes).hexdigest()
    free_thresh = float(meta.get("free_thresh", 0.196))
    if free_thresh > 0.196:
        raise ExchangeError(f"free_thresh {free_thresh} exceeds CORE maximum 0.196")
    payload: dict[str, Any] = {
        "sha256": sha256,
        "resolution": float(meta["resolution"]),
        "origin": [float(v) for v in meta["origin"]],
        "occupied_thresh": float(meta.get("occupied_thresh", 0.65)),
        "free_thresh": free_thresh,
        "pgm_base64": base64.b64encode(pgm_bytes).decode("ascii"),
        "grid_id": manifest.get("grid_id"),
        "source": args.source or str(manifest.get("source") or ""),
        "alignment": manifest.get("alignment"),
    }
    site_map_id = args.site_map_id or manifest.get("site_map_id")
    if site_map_id:
        payload["site_map_id"] = site_map_id
    if args.version is not None:
        payload["version"] = int(args.version)
    return client.request("PUT", "/api/fleet/site-map/master-grid", payload)


def cmd_push(client: FleetClient, args: argparse.Namespace) -> dict[str, Any]:
    if args.activate:
        client.timeout = max(client.timeout, 45.0)
    results = []
    for robot_id in args.robot:
        res = client.request(
            "POST", f"/api/fleet/robots/{robot_id}/master-map/push", {"activate": bool(args.activate)},
        )
        if args.activate:
            act = (res.get("robot_reply") or {}).get("activation")
            if isinstance(act, dict) and act.get("phase") not in (None, "ACTIVE"):
                raise ExchangeError(f"{robot_id} activation did not complete cleanly: {act}")
        results.append(res)
    return {"results": results}


def _robot_entries(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = state.get("robots")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {str(item["robot_id"]): item for item in raw if isinstance(item, dict) and "robot_id" in item}
    return {}


def cmd_verify_loc(client: FleetClient, args: argparse.Namespace) -> dict[str, Any]:
    expected_grid_id = args.expect_grid_id
    if not expected_grid_id:
        expected_grid_id = client.request("GET", "/api/fleet/site-map/master-grid")["grid_id"]
    deadline = time.monotonic() + max(0.0, float(args.wait_s))
    last_snapshot: dict[str, Any] = {}
    while True:
        entries = _robot_entries(client.request("GET", "/api/fleet/state"))
        last_snapshot = {}
        all_ok = True
        for rid in args.robot:
            r = entries.get(rid) or {}
            loc = r.get("localization") if isinstance(r.get("localization"), dict) else {}
            grid_id = r.get("map_grid_id")
            online = bool(r.get("online", True)) if r else False
            matched = (
                online
                and loc.get("state") == "LOCALIZED"
                and loc.get("pose_frame") == "map"
                and grid_id == expected_grid_id
            )
            last_snapshot[rid] = {
                "online": online,
                "localization_state": loc.get("state"),
                "pose_frame": loc.get("pose_frame"),
                "map_grid_id": grid_id,
                "matched": matched,
            }
            if not matched:
                all_ok = False
        if all_ok:
            return {"ok": True, "expected_grid_id": expected_grid_id, "robots": last_snapshot}
        if time.monotonic() >= deadline:
            raise ExchangeError(
                "localization verification timed out: "
                + json.dumps({"expected_grid_id": expected_grid_id, "robots": last_snapshot}, sort_keys=True)
            )
        time.sleep(max(0.05, float(args.poll_s)))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fleet-url", default="http://127.0.0.1:8090", help="Fleet base URL")
    ap.add_argument("--token", default=None, help="Fleet operator bearer token (or ROSY_FLEET_TOKEN env)")
    ap.add_argument("--ca", type=Path, default=None, help="CA certificate bundle for TLS Fleet URLs")
    ap.add_argument("--timeout", type=float, default=15.0)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="Pull one robot map bundle from Fleet and save PGM/YAML")
    p_pull.add_argument("--robot", required=True)
    p_pull.add_argument("--out-dir", type=Path, required=True)
    p_pull.add_argument("--name", default=None)

    p_up = sub.add_parser("upload", help="Verify sealed master bundle and upload to Fleet")
    p_up.add_argument("sealed_yaml", type=Path)
    p_up.add_argument("--site-map-id", default=None)
    p_up.add_argument("--version", type=int, default=None)
    p_up.add_argument("--source", default="")

    p_push = sub.add_parser("push", help="Push stored master map from Fleet to one or more robots")
    p_push.add_argument("--robot", action="append", required=True)
    p_push.add_argument("--activate", action="store_true")

    p_ver = sub.add_parser("verify-loc", help="Poll Fleet until robots are LOCALIZED on expected grid_id")
    p_ver.add_argument("--robot", action="append", required=True)
    p_ver.add_argument("--expect-grid-id", default=None)
    p_ver.add_argument("--wait-s", type=float, default=30.0)
    p_ver.add_argument("--poll-s", type=float, default=1.0)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    token = args.token if args.token is not None else os.environ.get("ROSY_FLEET_TOKEN", "")
    client = FleetClient(args.fleet_url, token=token, ca=args.ca, timeout=args.timeout)
    try:
        fn = {"pull": cmd_pull, "upload": cmd_upload, "push": cmd_push, "verify-loc": cmd_verify_loc}[args.cmd]
        out = fn(client, args)
    except (ExchangeError, OSError, KeyError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
