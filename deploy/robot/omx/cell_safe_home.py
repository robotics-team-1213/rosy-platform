#!/usr/bin/env python3
"""Unified guarded OMX arm safe-home & incident recovery (`POST /jobs/safe_home`).

Handles both active torque-ON `human-hold` sessions (via `--unlatch-hold`) and torque-OFF incident-held
arms (after verifying 0 latched hardware errors via read-only `register_probe`), using FK-safe tucked `park_path`
and post-fold `hardware_error == 0` evidence to clear up to 3 transient incidents when an assessor token exists.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

COOL_C = 45
DEFAULT_MAX_INCIDENTS = 3
BY_ID = Path("/dev/serial/by-id")


def _record_port(config_path: Path, cfg: dict) -> str | None:
    try:
        rec_path = (cfg.get("record") or {}).get("config")
        if rec_path:
            rp = Path(str(rec_path)).expanduser()
            if not rp.is_absolute() and not rp.is_file():
                rp = config_path.parent / rp
            rec = json.loads(rp.read_text(encoding="utf-8"))
            if port := ((rec.get("robot") or {}).get("port")):
                return str(port)
    except (OSError, ValueError, TypeError):
        pass
    return None


def _resolve_device(arm: str, config_path: Path, cfg: dict, explicit: str | None) -> tuple[str | None, str | None]:
    """(device, refusal): never a board the map gives another arm (2026-11-26 arm_b's record config named arm_a's
    OpenRB). The explicit or record port is used when the map gives it this arm (explicit: or no arm); an unmapped
    or missing record port falls back to the map's follower for the arm."""
    import omx_incident_reassess as reassess

    candidate = explicit or _record_port(config_path, cfg)
    if candidate:
        try:
            owner = reassess.board_arm(candidate, BY_ID)
        except (OSError, ValueError):
            return candidate, "refused_board_map_unavailable"
        if owner not in (None, arm):
            return candidate, "refused_device_arm_mismatch"
        if explicit or owner == arm:
            return candidate, None
    try:
        return str(reassess.follower(arm, by_id=BY_ID)[1]), None
    except (OSError, ValueError, SystemExit):
        return None, None


def _live_hold_active(config: dict, *, max_age_s: float = 15.0) -> bool:
    from cell_job_guards import pid_alive

    io_dir = Path(config.get("io", "")).expanduser()
    live_path = io_dir / "live.json"
    if not live_path.is_file():
        return False
    try:
        live = json.loads(live_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    t = live.get("t")
    pid = live.get("pid")
    return (
        isinstance(live, dict)
        and isinstance(t, (int, float))
        and not isinstance(t, bool)
        and abs(time.time() - float(t)) <= max_age_s
        and (pid is None or pid_alive(pid))
        and live.get("human_hold_latched") is True
        and live.get("torque_hold_commanded") is True
    )


def _release_observer(arm: str) -> None:
    try:
        subprocess.run([sys.executable, str(Path(__file__).resolve().with_name("observer_handoff.py")), "release", arm],
                       capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _rebootable_ids(rows, *, max_temp_c: int = COOL_C) -> list[int] | None:
    """Return sorted faulted IDs only when all 6 motors 11..16 read torque 0, temp < COOL_C, and rebootable hw_error."""
    import omx_incident

    if not isinstance(rows, list) or len(rows) != 6 or {r.get("id") for r in rows} != set(range(11, 17)):
        return None
    for r in rows:
        t = r.get("torque_enabled")
        if type(t) is not int or t != 0 or type(r.get("hardware_error")) is not int:
            return None
        temp = r.get("temperature")
        if type(temp) not in (int, float) or isinstance(temp, bool) or not math.isfinite(float(temp)) or float(temp) >= max_temp_c:
            return None
    bad = [r for r in rows if r["hardware_error"]]
    if not bad or any((r["hardware_error"] & ~omx_incident.REBOOTABLE) != 0 for r in bad):
        return None
    return sorted(int(r["id"]) for r in bad)


def _reboot_clean(after, ids: list[int]) -> bool:
    if not isinstance(after, dict) or not ids or any(type(i) is not int or i not in range(11, 17) for i in ids):
        return False
    for i in range(11, 17):
        entry = after.get(i) if i in after else after.get(str(i))
        if (not isinstance(entry, dict) or type(entry.get("torque")) is not int or entry["torque"] != 0
                or type(entry.get("hw_error")) is not int or entry["hw_error"] != 0):
            return False
    return True


def _check_hw_clean(
    arm: str, device: str | None, *, read_fn=None, stopped_out=None, reboot_fn=None, lock_fn=None,
) -> tuple[bool, list[dict], str | None, dict | None]:
    if read_fn is None and (not device or not Path(device).exists()):
        return False, [{"error": "follower device unresolved or missing"}], "refused_hw_probe_unavailable", None
    import omx_incident
    import register_probe

    lock = None
    stopped_obs = False
    try:
        try:
            if read_fn is None:
                import joint_tune_lock
                import omx_incident_reassess

                lock = (lock_fn or joint_tune_lock.session_lock)(arm)
                stopped_obs = omx_incident_reassess.pause_observer_if_sole_holder(arm, device)
                if stopped_out is not None:
                    stopped_out.append(stopped_obs)
            if read_fn is not None:
                rows = read_fn(device)
            else:
                with register_probe.open_readonly_port(device) as port:
                    rows = register_probe.read_motors(port, allow_fault=True)
        except (Exception, SystemExit) as exc:
            if lock is not None:
                lock.close()
                lock = None
            if stopped_obs:
                _release_observer(arm)
                if stopped_out is not None:
                    stopped_out.clear()
            msg = str(exc)
            reason = "refused_hw_error" if ("hardware alert" in msg or ("ping failed" in msg and ", 128)" in msg)) else "refused_hw_probe_unavailable"
            return False, [{"error": f"{type(exc).__name__}: {msg}"[:200]}], reason, None
        bad = [r for r in rows if r.get("hardware_error")]
        if bad:
            ids = _rebootable_ids(rows)
            reboot_receipt = None
            if ids:
                try:
                    reboot_receipt = (reboot_fn or omx_incident.reboot_latched(device))(ids)
                except (Exception, SystemExit) as exc:
                    reboot_receipt = {"error": f"{type(exc).__name__}: {exc}"[:160]}
                if isinstance(reboot_receipt, dict) and reboot_receipt.get("rebooted") == ids and _reboot_clean(reboot_receipt.get("after"), ids):
                    return True, [], None, reboot_receipt
            if lock is not None:
                lock.close()
                lock = None
            if stopped_obs:
                _release_observer(arm)
                if stopped_out is not None:
                    stopped_out.clear()
            return False, bad, "refused_hw_error", reboot_receipt
        return True, [], None, None
    finally:
        if lock is not None:
            lock.close()


check_and_reboot_hw_clean = _check_hw_clean


def _write_out(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def run_safe_home(args, *, read_fn=None, status_fn=None, clear_fn=None, run_fn=None, token_fn=None,
                  live_fn=None, wait_sess_fn=None, lease_status_fn=None, reboot_fn=None, lock_fn=None,
                  now=time.time, sleep=time.sleep) -> tuple[int, dict]:
    import cell_arm_lease
    import cell_auto_fold as af
    from cell_job_spec import SESSION
    from cell_recovery_plan import wait_session_json
    import omx_incident
    import omx_incident_auto

    cfg_path = Path(args.config).expanduser()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out_path = Path(args.out)
    fold_cmd = [
        sys.executable, str(Path(__file__).resolve().parent / "cell_auto_fold.py"),
        "--supervised", "--arm", args.arm, "--config", str(args.config), "--library", str(args.library),
        "--site", args.site, "--roi", *map(str, args.roi), "--out", str(out_path),
    ]
    def _read_out(proc, default_result: str, extra: dict | None = None) -> dict:
        if out_path.is_file():
            try:
                return json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        payload = {"result": default_result, "reason": f"process exited {proc.returncode} before writing safe_home output",
                   "arm": args.arm, "returncode": proc.returncode, **(extra or {})}
        _write_out(out_path, payload)
        return payload

    device, device_refusal = _resolve_device(args.arm, cfg_path, cfg, args.device)
    if device_refusal:  # before any fold: the fold and its session would command the same wrong board
        res = {"result": device_refusal, "arm": args.arm, "device": device}
        _write_out(out_path, res)
        return 2, res
    out_path.unlink(missing_ok=True)
    is_live = (live_fn or _live_hold_active)(cfg)
    if is_live:
        proc = (run_fn or subprocess.run)([*fold_cmd, "--unlatch-hold"], timeout=3600)
        out = _read_out(proc, "failed", {"mode": "live_hold_unlatch"})
        return proc.returncode, {**out, "mode": "live_hold_unlatch"}

    lease_fn = lease_status_fn if lease_status_fn is not None else (cell_arm_lease.status if read_fn is None else None)
    if lease_fn is not None:
        rec = (lease_fn(args.arm) or {}).get(args.arm)
        if rec and rec.get("hold"):
            res = {"result": "refused_lease_held", "arm": args.arm, "owner": rec.get("owner"),
                   "hold": rec.get("hold"), "pid": rec.get("pid")}
            _write_out(out_path, res)
            return 2, res

    stopped_obs: list[bool] = []
    hw_ok, bad, refuse_reason, reboot_receipt = _check_hw_clean(
        args.arm, device, read_fn=read_fn, stopped_out=stopped_obs, reboot_fn=reboot_fn, lock_fn=lock_fn,
    )
    if not hw_ok:
        res = {"result": refuse_reason or "refused_hw_error", "arm": args.arm, "device": device, "bad_motors": bad,
               **({"reboot_attempt": reboot_receipt} if reboot_receipt is not None else {})}
        _write_out(out_path, res)
        return 2, res

    def _release_if_paused() -> None:
        if stopped_obs and stopped_obs[0]:
            _release_observer(args.arm)
            stopped_obs.clear()

    try:
        st = (status_fn or omx_incident.status)(args.arm)
        ids = list(st.get("incident_ids") or [])
        if len(ids) > args.max_incidents:
            _release_if_paused()
            res = {"result": "refused_too_many_incidents", "arm": args.arm, "incident_ids": ids}
            _write_out(out_path, res)
            return 2, res

        wrapper = SESSION.get(args.arm)
        if not wrapper:
            _release_if_paused()
            res = {"result": "refused_no_wrapper", "arm": args.arm}
            _write_out(out_path, res)
            return 2, res
        env = dict(os.environ)
        env["ROSY_SESSION_CHUNKS"] = str(Path(args.library).expanduser().resolve())
        if ids:
            env["ROSY_RECOVERY_INCIDENT"] = ",".join(ids)
        started = now()
        proc = (run_fn or subprocess.run)([wrapper, *fold_cmd], env=env, timeout=3600)
        out = _read_out(proc, "session_start_failed")
        if proc.returncode != 0 or out.get("result") != "folded":
            _release_if_paused()
            if reboot_receipt is not None:
                out["rebooted_ids"] = reboot_receipt["rebooted"]
                _write_out(out_path, out)
            return (proc.returncode or 3), out
    except BaseException:
        _release_if_paused()
        raise

    cleared_ids, clear_errors = [], {}
    if ids and not args.no_clear:
        sess, why = (wait_sess_fn or wait_session_json)(Path.cwd() / "session.json", args.arm, started, sleep)
        token = (token_fn or omx_incident_auto.assessor_token_file)()
        if sess is None or token is None:
            out.update(clear_skipped=why or "no assessor token")
        else:
            torque = sess.get("torque_after") or {}
            hw_after = {str(k): 0 for k in torque} if sess.get("hardware_faults") == {} and len(torque) >= 6 else None
            caps_ok = sess.get("caps_restored") if isinstance(sess.get("caps_restored"), bool) else None
            note = f"safe_home (unified recovery): {out.get('candidate')}, home within {af.SETTLE_TOL} units, torque OFF"
            for inc_id in ids:
                proof = af.evidence(out, out["home"], torque, inc_id, now(),
                                    hardware_error_after=hw_after, caps_restored_after=caps_ok)
                try:
                    (clear_fn or omx_incident.clear)(
                        args.arm, note, token, cause="unknown", basis="measured", recovery=proof, only=inc_id,
                    )
                    cleared_ids.append(inc_id)
                except (SystemExit, Exception) as exc:  # noqa: BLE001
                    clear_errors[inc_id] = f"{type(exc).__name__}: {str(exc)[:160]}"
            out.update(cleared_ids=cleared_ids, clear_errors=clear_errors)
            if clear_errors:
                out["clear_failed"] = True
    if reboot_receipt is not None:
        out["rebooted_ids"] = reboot_receipt["rebooted"]
    _write_out(Path(args.out), out)
    return (4 if clear_errors else 0), out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default=None)
    ap.add_argument("--max-incidents", type=int, default=DEFAULT_MAX_INCIDENTS)
    ap.add_argument("--no-clear", action="store_true")
    ap.add_argument("--operator", default=None)
    ap.add_argument("--proposer", default=None)
    args = ap.parse_args(argv)
    rc, out = run_safe_home(args)
    summary_keys = ("result", "reason", "candidate", "rebooted_ids", "cleared_ids", "clear_errors", "clear_failed", "clear_skipped")
    print(json.dumps({"arm": args.arm, **{k: out.get(k) for k in summary_keys if k in out}}, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
