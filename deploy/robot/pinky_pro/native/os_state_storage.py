"""Read-only storage gate before network services can use cached device state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from os_state_firstboot import FirstBootState
from os_state_layout import TLS_PENDING, _path


def admit_storage(root: Path, *, require_no_pending: bool = False) -> dict:
    shared = FirstBootState.admit(root)
    if shared is None:
        return {"schema_version": 1, "phase": "LEGACY"}
    phase = shared.validate_storage_state()
    if require_no_pending and _path(Path(root), TLS_PENDING).exists():
        raise ValueError("TLS transaction pending")
    return {"schema_version": 1, "phase": phase, "slot": shared.layout["slot"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--no-pending-maintenance", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = admit_storage(args.root, require_no_pending=args.no_pending_maintenance)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_STATE_HOLD"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
