#!/usr/bin/env python3
"""Read-only check of one leader/follower OMX cell before joint_tune or record_session.

Nothing is written to a motor. Each failed check carries the command that fixes it, so a remote
operator gets one verdict instead of finding the next refusal one tool at a time (2026-10-24:
missing board, caps left raised in EEPROM, camera readiness stopped after a boot refusal).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from register_probe import collect

READINESS = Path.home() / ".local/state/rosy/omx-camera-environment/readiness.json"
RESTING = {"pwm_limit_raw": 20, "current_limit_raw": 50}  # joint_tune.BASELINE in register units


def judge_motors(rows, device):
    checks = []
    for row in rows:
        motor, problems = row["id"], []
        if row["torque_enabled"]:
            problems.append("torque ON")
        if row["hardware_error"]:
            problems.append(f"hardware error {row['hardware_error']}")
        if not row["min_voltage_raw"] <= row["voltage_raw"] <= row["max_voltage_raw"]:
            problems.append(f"voltage {row['voltage_raw'] / 10} V outside "
                            f"{row['min_voltage_raw'] / 10}-{row['max_voltage_raw'] / 10} V")
        checks.append(dict(name=f"follower {motor} state", ok=not problems, detail=", ".join(problems) or "ok"))
        raised = {name: row[name] for name, value in RESTING.items()
                  if row[name] is not None and row[name] != value}
        checks.append(dict(name=f"follower {motor} caps", ok=not raised, detail=raised or "resting",
                           **({"fix": f"commissioning_limits.py --device {device} --baseline "
                                      "--output <new receipt dir>"} if raised else {})))
    return checks


def judge_readiness(path):
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        state = {"state": f"unreadable: {error}"}
    ready = state.get("state") == "READY" and state.get("photometric_ready") is True
    return dict(name="camera readiness", ok=ready, detail=state.get("state"),
                **({} if ready else {"fix": "systemctl --user restart rosy-omx-camera-readiness"}))


def check(follower, leader, readiness=READINESS, *, read=collect):
    checks = [dict(name=f"{role} board", ok=Path(device).exists(), detail=device,
                   **({} if Path(device).exists() else {"fix": "connect and power the board, then re-grant serial access"}))
              for role, device in (("follower", follower), ("leader", leader))]
    # shortcut: the leader is checked for presence only; register_probe reads follower IDs 11-16 alone.
    if checks[0]["ok"]:
        try:
            checks += judge_motors(read(follower), follower)
        except Exception as error:  # busy bus, missing motor, unsupported model
            checks.append(dict(name="follower registers", ok=False, detail=str(error),
                               fix="stop the process holding the bus (observer, session) and check all six motors answer"))
    checks.append(judge_readiness(readiness))
    return {"scope": "readonly_cell_check", "motion_admitted": False,
            "ok": all(c["ok"] for c in checks), "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--follower", required=True, help="follower /dev/serial/by-id path")
    parser.add_argument("--leader", required=True, help="leader /dev/serial/by-id path")
    parser.add_argument("--readiness", type=Path, default=READINESS)
    args = parser.parse_args(argv)
    report = check(args.follower, args.leader, args.readiness)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
