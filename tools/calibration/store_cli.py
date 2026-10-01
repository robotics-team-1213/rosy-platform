"""Operator view of the versioned calibration store (core_common/calibration_store.py).

    store_cli.py list   ROBOT [KIND]            records with status, the current one marked
    store_cli.py show   ROBOT KIND RECORD
    store_cli.py accept ROBOT KIND RECORD --actor NAME [--note TEXT] [--hand-deg D]
    store_cli.py reject ROBOT KIND RECORD --actor NAME [--note TEXT]
    store_cli.py pin    ROBOT KIND RECORD|none --actor NAME [--note TEXT]   (rollback / unpin)
    store_cli.py sync   ROBOT --from OTHER_ROOT                              (merge another copy in)

--root defaults to the PC mirror data/calibration/ (gitignored). On the robot
the store is /var/lib/rosy/calibration/ (root-owned, group rosy-calib, mode
2775; D-47 addendum 2026-10-01). Moving records between the two is a merge,
never a folder copy: pull the robot's <robot>/ folder to a staging root, run
`sync ROBOT --from <staging>` here, then `sync` the other way on a staging
copy and put that back. sync copies only record files that are missing
(identical ids must be byte-identical) and appends only missing events.

accept refuses implausible values with the same check the runtime applies
(lidar_mount within 150-210 deg, or within 15 deg of --hand-deg when given; wheels within 10 %
of the URDF nominal 0.028 m / 0.0971 m (D-397); camera pitch/height in range). Accepting is the
operator's decision; nothing else accepts a record. accept, reject and pin
happen on the PC mirror only; the robot store receives them through sync
(a sync that finds decisions on both sides refuses).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "contracts" / "foundation"))

from core_common.calibration_store import KINDS, CalibrationStore, check_values  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("list", "show", "accept", "reject", "pin", "sync"))
    ap.add_argument("robot")
    ap.add_argument("kind", nargs="?", choices=KINDS)
    ap.add_argument("record", nargs="?")
    ap.add_argument("--root", type=Path, default=REPO / "data" / "calibration")
    ap.add_argument("--from", dest="other", type=Path, help="sync: the other store root")
    ap.add_argument("--actor", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--hand-deg", type=float, default=None,
                    help="accept lidar_mount: the robot's line_follow hand value; needed only when it "
                         "lies outside 165-195 deg (default: the 150-210 deg window alone)")
    args = ap.parse_args(argv)
    try:
        return _run(ap, args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


def _run(ap, args) -> int:
    store = CalibrationStore(args.root)
    if args.action == "list":
        for kind in [args.kind] if args.kind else KINDS:
            for rec in store.records(args.robot, kind):
                mark = "*" if rec.get("current") else " "
                print(f"{mark} {kind:15s} {rec['id']:40s} {rec['status']:10s} "
                      f"{json.dumps(rec.get('values', {}), sort_keys=True)[:100]}")
        return 0
    if args.action == "sync":
        if args.other is None:
            ap.error("sync needs --from OTHER_ROOT")
        print(store.merge_from(args.other, args.robot))
        return 0
    if not args.kind or not args.record:
        ap.error("kind and record are required")
    if args.action == "show":
        print(json.dumps(store.load(args.robot, args.kind, args.record), indent=1))
    elif args.action == "accept":
        rec = store.load(args.robot, args.kind, args.record)
        why = check_values(args.kind, rec["values"], nominal={} if args.hand_deg is None else {"lidar_forward_deg": args.hand_deg})
        if why:
            print(f"refused: {why}", file=sys.stderr)
            return 2
        store.set_status(args.robot, args.kind, args.record, "accepted", actor=args.actor, note=args.note)
    elif args.action == "reject":
        store.set_status(args.robot, args.kind, args.record, "rejected", actor=args.actor, note=args.note)
    else:
        store.pin(args.robot, args.kind, None if args.record == "none" else args.record,
                  actor=args.actor, note=args.note)
    current = store.current(args.robot, args.kind)
    print(f"current {args.kind}: {current['id'] if current else 'none (static fallback)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
