"""Torque OFF for a folded follower arm, then the baseline caps, as one pipeline job (2026-11-26).

A USB hub drop with live 12 V leaves the last session's torque ON, and record_session.check_idle then refuses every
session ("follower 11 not idle: torque 1", later "caps not the baseline"). This job does by hand what was done over ssh:
no person at the switch is needed because only a folded arm (cell_job_peer_health fold rule on calibrated present positions) is released, an extended arm is
refused with NOT_FOLDED before any write. Locks follow the observer unit: session.lock shared, session-<arm>.lock exclusive.
The last stdout line is the structured result JSON.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cell_incident_release  # noqa: E402
from cell_job_peer_health import calibrated_positions_folded, fold_basis  # noqa: E402
from record_session_baseline import BaselineMismatch  # noqa: E402

MOTORS = tuple(range(11, 17))
REJECTED, ERROR = 2, 3  # exit codes; 0 = torque OFF confirmed and baseline caps verified
CAL_DIR = Path.home() / ".cache/huggingface/lerobot/calibration/robots/omx_follower"


class Refused(Exception):
    def __init__(self, code, message, exit_code=REJECTED):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def snapshot(bus) -> dict:
    out = {}
    for motor in MOTORS:
        bus.motor = motor
        out[motor] = {"torque": bus.read("torque"), "position": bus.read("present_pos")}
    return out


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_baseline(device: str, out_dir: Path) -> int:
    here = Path(__file__).resolve().parent
    return subprocess.run([sys.executable, str(here / "commissioning_limits.py"), "--device", device, "--baseline",
                           "--output", str(out_dir)], stdin=subprocess.DEVNULL, timeout=120).returncode


def release(arm, device, *, open_bus, lock, session, calibration, baseline, out_dir, result=None, library=None) -> dict:
    """Result dict; raises Refused with a reason code. `session` supplies torque_off_until_confirmed/check_idle."""
    result = {} if result is None else result  # the caller keeps it, so a refusal still reports before/after
    result.update(arm=arm, device=device, fold_basis=fold_basis(library))
    try:
        guard = lock(arm)
    except SystemExit as exc:
        raise Refused("SESSION_LOCK_HELD", str(exc)) from None
    try:
        try:
            bus = open_bus()
        except Exception as exc:
            raise Refused("PORT_OPEN_FAILED", f"cannot open {device}: {exc}", ERROR) from None
        try:
            result["before"] = before = snapshot(bus)
        except Exception as exc:
            raise Refused("READ_FAILED", f"cannot read follower: {exc}", ERROR) from None
        finally:
            bus.close()
        if calibration is None:
            raise Refused("CALIBRATION_MISSING", f"no calibration for {arm}: fold cannot be judged")
        already_off = all(before[m]["torque"] == 0 for m in MOTORS)
        result["already_torque_off"] = already_off
        if not already_off:  # the fold rule guards the torque cut; an arm already OFF only gets its caps written (no motion)
            if not calibrated_positions_folded([before[m]["position"] for m in MOTORS], calibration, library):
                raise Refused("NOT_FOLDED", "arm is not folded: torque is not cut on an extended arm")
            try:  # the pose may have changed since the first read: judge again right before the write
                bus = open_bus()
                try:
                    now = snapshot(bus)
                finally:
                    bus.close()
            except Exception as exc:
                raise Refused("READ_FAILED", f"cannot re-read follower: {exc}", ERROR) from None
            if not calibrated_positions_folded([now[m]["position"] for m in MOTORS], calibration, library):
                raise Refused("NOT_FOLDED", "arm left the folded pose before torque OFF")
            ok, state = session.torque_off_until_confirmed()
            if not ok:
                raise Refused("TORQUE_OFF_UNCONFIRMED", f"torque OFF not confirmed: {state}", ERROR)
        restored = False
        while True:
            try:
                result["after"] = session._with_follower(lambda b: (session.check_idle(b), snapshot(b))[1])
                result["baseline"] = {"restored": restored}
                result["folded_after"] = calibrated_positions_folded([result["after"][m]["position"] for m in MOTORS], calibration, library)
                return result
            except BaselineMismatch as exc:  # a SystemExit: caps an earlier session left raised
                if restored or baseline(device, out_dir) != 0:
                    raise Refused("BASELINE_NOT_RESTORED", str(exc), ERROR) from None
                restored = True
            except (SystemExit, Exception) as exc:  # torque/hw_error/model: not idle after the confirmed OFF
                raise Refused("NOT_IDLE", str(exc), ERROR) from None
    finally:
        guard.close()


def main(argv=None, **inject) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--config", required=True, type=Path, help="record config JSON; robot.port is the follower by-id")
    parser.add_argument("--library", type=Path, help="the arm's chunks-*.json (or cell config): narrows the fold rule to its park/home/standby poses")
    parser.add_argument("--out-dir", type=Path, default=Path("cell-job-api"))
    args = parser.parse_args(argv)
    import joint_tune
    import record_session
    robot = (_read_json(args.config) or {}).get("robot", {})
    device = robot.get("port", "")
    out = {"job": "torque_off_folded", "arm": args.arm, "ok": False, "principal": os.environ.get("ROSY_JOB_PRINCIPAL"), "at": time.time()}
    try:
        if robot.get("id") != f"{args.arm}_follower":  # the lock and calibration follow --arm, the port follows the config
            raise Refused("ARM_CONFIG_MISMATCH", f"{args.config}: robot.id is {robot.get('id')!r}, not {args.arm}_follower")
        if not str(device).startswith("/dev/serial/by-id/"):
            raise Refused("NO_DEVICE", f"{args.config}: robot.port is not a /dev/serial/by-id path")
        open_bus = inject.get("open_bus") or (lambda: joint_tune.SerialBus(device, 0))
        session = inject.get("session") or record_session.Session(
            open_bus=lambda which: open_bus(), systemctl=lambda *a: "", run=None, log=lambda **k: None)
        lib = inject.get("library", _read_json(args.library) if args.library else None)
        if args.library and fold_basis(lib) == "coarse":  # a library was named but gives no fold poses: do not fall back silently
            raise Refused("LIBRARY_UNUSABLE", f"{args.library}: no usable park/home/standby pose")
        res = release(args.arm, device, open_bus=open_bus, lock=inject.get("lock") or joint_tune.session_lock, session=session,
                      calibration=inject.get("calibration", _read_json(CAL_DIR / f"{args.arm}_follower.json")),
                      baseline=inject.get("baseline") or run_baseline,
                      out_dir=args.out_dir / f"baseline-{args.arm}-{int(time.time())}", result=out,
                      library=lib)
        out.update(ok=True, reason_code=None)
        code = 0
        # shortcut: injected runs skip the release; production calls main() bare
        if (hook := inject.get("release", None if inject else cell_incident_release.after_torque_off)) is not None:
            try:
                out["incident_release"] = hook(args.arm)
            except (SystemExit, Exception) as exc:  # the torque-off result above stands either way
                out["incident_release"] = {"cleared": False, "why": f"{type(exc).__name__}: {str(exc)[:120]}"}
    except Refused as exc:
        out.update(ok=False, reason_code=exc.code, error=str(exc))
        code = exc.exit_code
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
