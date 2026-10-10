#!/usr/bin/env python3
"""D-426 Task 1 runner — plans one isolated Fleet–Gazebo conformance run.

This command creates the run root, manifest, per-robot CORE overlays, and the
fleet robots manifest with runtime-generated tokens. It prints the exact
launch and console commands; it does not execute them yet (execution wiring
lands with Tasks 5–6). Tokens are generated per run and live only inside the
run root (plan §공통 실행 규칙 4) — nothing here touches a real device.

    python tools/validation/fleet_gazebo/run.py --robots 2 --scenario all \
        --output-root /mnt/x/DevTemp/fleet-gazebo
"""

from __future__ import annotations

import argparse
import secrets
import shlex
import sys
import time
from pathlib import Path

import yaml

from preflight import (MANIFEST_NAME, PreflightError, Reservations,
                       check_no_symlink_escape, check_overlays, check_reservations,
                       require_file_hashes, validate_run_root, write_manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fleet_gazebo.run",
        description="Plan an isolated Fleet-Gazebo conformance run (D-426 T1).")
    parser.add_argument("--robots", type=int, default=2,
                        help="sim robots (rosy_01..NN), 1..8")
    parser.add_argument("--scenario", default="all",
                        help="scenario id or 'all' (M01-M08 are wired in later tasks)")
    parser.add_argument("--output-root", required=True,
                        help="run roots are created under this directory")
    parser.add_argument("--run-id", default=None,
                        help="unique run id (default run-YYYYmmdd-HHMMSS)")
    parser.add_argument("--world", required=True, help="world file (hashed into the manifest)")
    parser.add_argument("--map", required=True, help="map yaml (hashed into the manifest)")
    parser.add_argument("--profile", required=True,
                        help="robot profile yaml (hashed into the manifest)")
    parser.add_argument("--source-root", default=None,
                        help="repository root for the recorded argv (default: this file's tree)")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_id = args.run_id or time.strftime("run-%Y%m%d-%H%M%S")
    output_root = Path(args.output_root)
    if output_root.exists() and output_root.is_symlink():
        print(f"preflight: output root must not be a symlink: {output_root}",
              file=sys.stderr)
        return 2

    started_at = time.time()
    try:
        reservations = Reservations.derive(run_id, args.robots, started_at=started_at)
        hashes = require_file_hashes({
            "world": Path(args.world),
            "map": Path(args.map),
            "profile": Path(args.profile),
        })
        root = output_root / run_id
        validate_run_root(root)
        check_reservations(output_root, reservations)
        write_manifest(root, reservations, versions={}, hashes=hashes,
                       argv=[parser.prog] + sys.argv[1:])

        # Runtime tokens: operator token (CORE REST, fleet console side) and the
        # pairing token (CORE FleetAgent → hub WS) never leave the run root.
        operator_token = "val-" + secrets.token_hex(16)
        robots_rows = []
        for ns, api_port in zip(reservations.namespaces, reservations.api_ports):
            pairing_token = "pair-" + secrets.token_hex(16)
            overlay = {
                "robot": {"id": ns},
                "network": {"api_host": "127.0.0.1", "api_port": int(api_port)},
                "auth": {"tokens": [
                    {"token": operator_token, "role": "operator",
                     "label": f"d426 validation run {run_id}"},
                ]},
                "fleet": {"hub_url": reservations.hub_url,
                          "pairing_token": pairing_token},
            }
            (root / f"core_{ns}.yaml").write_text(
                yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
            robots_rows.append({
                "robot_id": ns,
                "base_url": f"http://127.0.0.1:{api_port}",
                "token": operator_token,
                "fleet_pairing_token": pairing_token,
            })
        manifest = {"robots": robots_rows}
        robots_path = root / "robots.yaml"
        robots_path.write_text(yaml.safe_dump(manifest, sort_keys=False),
                               encoding="utf-8")

        # Self-check before reporting the commands: overlays and manifest agree,
        # and the run root is free of symlink escapes.
        check_overlays(root, reservations.namespaces, reservations.hub_url, manifest)
        check_no_symlink_escape(root)
    except PreflightError as exc:
        print(f"preflight: {exc}", file=sys.stderr)
        return 2

    run_spec = root / "run_spec.yaml"
    run_spec.write_text(yaml.safe_dump({
        "run_id": run_id,
        "manifest": str(root / MANIFEST_NAME),
        "core_config_dir": str(root),
        "fleet_manifest": str(robots_path),
        "hub_url": reservations.hub_url,
        "console_port": reservations.console_port,
        "ros_domain_id": reservations.ros_domain_id,
        "gz_partition": reservations.gz_partition,
        "robots": [{"namespace": ns, "api_port": int(port)}
                   for ns, port in zip(reservations.namespaces, reservations.api_ports)],
    }, sort_keys=False), encoding="utf-8")

    print(f"run root:   {root}")
    print(f"run spec:   {run_spec}")
    environment = (f"env ROS_DOMAIN_ID={reservations.ros_domain_id} "
                   f"GZ_PARTITION={shlex.quote(reservations.gz_partition)}")
    print(f"gz launch:  {environment} ros2 launch gz_sim gz_multi.launch.py robots:={args.robots} "
          f"prefix:=rosy core:=true {shlex.quote('run_spec:=' + str(run_spec))}")
    print(f"fleet:      {environment} python operations/fleet/fleet/cli.py console "
          f"--robots {shlex.quote(str(robots_path))} --port {reservations.console_port} "
          f"--tasks-db {shlex.quote(str(root / 'tasks.sqlite3'))} "
          f"--events-db {shlex.quote(str(root / 'events.sqlite3'))} "
          "--site-map-import middleware/perception/map/map_v2_fleet/lane_graph.yaml "
          "--site-config integrations/simulation/gazebo/config/fleet_sim_site.yaml")
    print("READY is decided by preflight probes (clock/scan/odom/tf/nav2/"
          "core_http/ws_welcome) — not by this planner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
