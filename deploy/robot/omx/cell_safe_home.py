#!/usr/bin/env python3
"""Unified guarded OMX arm safe-home & incident recovery (`POST /jobs/safe_home`).

Handles both active torque-ON `human-hold` sessions (via `--unlatch-hold`) and torque-OFF incident-held
arms (after verifying 0 latched hardware errors via read-only `register_probe`), using FK-safe tucked `park_path`
and post-fold `hardware_error == 0` evidence to clear up to 3 transient incidents when an assessor token exists.
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

DEFAULT_MAX_INCIDENTS = 3


def _resolve_device(arm: str, config_path: Path, cfg: dict, explicit: str | None) -> str | None:
    if explicit:
        return explicit
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
    try:
        import omx_incident_reassess

        return str(omx_incident_reassess.follower(arm)[1])
    except (OSError, ValueError, SystemExit):
        return None


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


def _check_hw_clean(arm: str, device: str | None, *, read_fn=None) -> tuple[bool, list[dict], str | None]:
    if read_fn is None and (not device or not Path(device).exists()):
        return False, [{"error": "follower device unresolved or missing"}], "refused_hw_probe_unavailable"
    import register_probe

    stopped_obs = False
    if read_fn is None:
        unit = f"rosy-omx-observer@{arm}.service"
        res = subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, check=False, timeout=10)
        stopped_obs = res.returncode == 0
    try:
        if read_fn is not None:
            rows = read_fn(device)
        else:
            with register_probe.open_readonly_port(device) as port:
                rows = register_probe.read_motors(port, allow_fault=True)
    except Exception as exc:  # noqa: BLE001
        if stopped_obs:
            _release_observer(arm)
        msg = str(exc)
        reason = "refused_hw_error" if ("hardware alert" in msg or ("ping failed" in msg and ", 128)" in msg)) else "refused_hw_probe_unavailable"
        return False, [{"error": f"{type(exc).__name__}: {msg}"[:200]}], reason
    bad = [r for r in rows if r.get("hardware_error")]
    if bad:
        if stopped_obs:
            _release_observer(arm)
        return False, bad, "refused_hw_error"
    return True, [], None


def _write_out(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def run_safe_home(args, *, read_fn=None, status_fn=None, clear_fn=None, run_fn=None, token_fn=None,
                  live_fn=None, wait_sess_fn=None, now=time.time, sleep=time.sleep) -> tuple[int, dict]:
    import cell_auto_fold as af
    from cell_job_spec import SESSION
    from cell_recovery_plan import wait_session_json
    import omx_incident
    import omx_incident_auto

    cfg_path = Path(args.config).expanduser()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    fold_cmd = [
        sys.executable, str(Path(__file__).resolve().parent / "cell_auto_fold.py"),
        "--supervised", "--arm", args.arm, "--config", str(args.config), "--library", str(args.library),
        "--site", args.site, "--roi", *map(str, args.roi), "--out", str(args.out),
    ]
    is_live = (live_fn or _live_hold_active)(cfg)
    if is_live:
        proc = (run_fn or subprocess.run)([*fold_cmd, "--unlatch-hold"], timeout=3600)
        out = json.loads(Path(args.out).read_text(encoding="utf-8")) if Path(args.out).is_file() else {}
        return proc.returncode, {**out, "mode": "live_hold_unlatch"}

    device = _resolve_device(args.arm, cfg_path, cfg, args.device)
    hw_ok, bad, refuse_reason = _check_hw_clean(args.arm, device, read_fn=read_fn)
    if not hw_ok:
        res = {"result": refuse_reason or "refused_hw_error", "arm": args.arm, "device": device, "bad_motors": bad}
        _write_out(Path(args.out), res)
        return 2, res

    st = (status_fn or omx_incident.status)(args.arm)
    ids = list(st.get("incident_ids") or [])
    if len(ids) > args.max_incidents:
        if read_fn is None:
            _release_observer(args.arm)
        res = {"result": "refused_too_many_incidents", "arm": args.arm, "incident_ids": ids}
        _write_out(Path(args.out), res)
        return 2, res

    wrapper = SESSION.get(args.arm)
    if not wrapper:
        if read_fn is None:
            _release_observer(args.arm)
        res = {"result": "refused_no_wrapper", "arm": args.arm}
        _write_out(Path(args.out), res)
        return 2, res
    env = dict(os.environ)
    if ids:
        env["ROSY_RECOVERY_INCIDENT"] = ",".join(ids)
    started = now()
    proc = (run_fn or subprocess.run)([wrapper, *fold_cmd], env=env, timeout=3600)
    out = json.loads(Path(args.out).read_text(encoding="utf-8")) if Path(args.out).is_file() else {"result": "failed"}
    if proc.returncode != 0 or out.get("result") != "folded":
        return (proc.returncode or 3), out

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
    _write_out(Path(args.out), out)
    return 0, out


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
    print(json.dumps({"arm": args.arm, **{k: out.get(k) for k in ("result", "reason", "candidate", "cleared_ids", "clear_errors", "clear_skipped") if k in out}}, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
