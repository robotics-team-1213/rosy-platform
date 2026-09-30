"""Operator view of the versioned calibration store (core_common/calibration_store.py).

    store_cli.py list   ROBOT [KIND]            records with status, the current one marked
    store_cli.py show   ROBOT KIND RECORD
    store_cli.py accept ROBOT KIND RECORD --actor NAME [--note TEXT]
    store_cli.py reject ROBOT KIND RECORD --actor NAME [--note TEXT]
    store_cli.py pin    ROBOT KIND RECORD|none --actor NAME [--note TEXT]   (rollback / unpin)

--root defaults to the PC mirror data/calibration/ (gitignored); on the robot
the store is /var/lib/rosy/calibration/. Accepting is the operator's decision;
nothing else accepts a record. KIND: camera_profile, wheel_odometry, lidar_mount.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "contracts" / "foundation"))

from core_common.calibration_store import KINDS, CalibrationStore  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("list", "show", "accept", "reject", "pin"))
    ap.add_argument("robot")
    ap.add_argument("kind", nargs="?", choices=KINDS)
    ap.add_argument("record", nargs="?")
    ap.add_argument("--root", type=Path, default=REPO / "data" / "calibration")
    ap.add_argument("--actor", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    store = CalibrationStore(args.root)
    if args.action == "list":
        for kind in [args.kind] if args.kind else KINDS:
            for rec in store.records(args.robot, kind):
                mark = "*" if rec.get("current") else " "
                print(f"{mark} {kind:15s} {rec['id']:40s} {rec['status']:10s} "
                      f"{json.dumps(rec.get('values', {}), sort_keys=True)[:100]}")
        return 0
    if not args.kind or not args.record:
        ap.error("kind and record are required")
    if args.action == "show":
        print(json.dumps(store.load(args.robot, args.kind, args.record), indent=1))
    elif args.action in ("accept", "reject"):
        store.set_status(args.robot, args.kind, args.record, "accepted" if args.action == "accept" else "rejected",
                         actor=args.actor, note=args.note)
    else:
        store.pin(args.robot, args.kind, None if args.record == "none" else args.record,
                  actor=args.actor, note=args.note)
    current = store.current(args.robot, args.kind)
    print(f"current {args.kind}: {current['id'] if current else 'none (static fallback)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
