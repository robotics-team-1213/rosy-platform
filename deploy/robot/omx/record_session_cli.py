#!/usr/bin/env python3
"""CLI Argument Parser, Child Recorder Process & Incident Hook for `record_session.py` (`record_session_cli.py`).

Single Responsibility:
  - Parse `record_session` CLI arguments, compose task card, spawn child recorder process with SIGINT/kill cleanup,
    and run post-session motor health snapshot + `omx_incident.after_session` hook (`main`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess as _std_subprocess
import sys
import time
from uuid import uuid4

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from joint_tune import SerialBus as _DefaultSerialBus, no_interrupts, protect_signals, session_lock  # noqa: E402
from record_session_helpers import compose, interrupt_on_parent_death, load_task_card, static_episodes  # noqa: E402
from session_caps import load_caps, model_tuning, robot_tuning  # noqa: E402


_PARENT_GLOBALS_LIST: list[dict] = []


def _REGISTER_GLOBALS(g: dict) -> None:
    if g not in _PARENT_GLOBALS_LIST:
        _PARENT_GLOBALS_LIST.append(g)


def _parent_attr(name: str, default=None, _globals: dict | None = None):
    if _globals is not None and name in _globals and _globals[name] != default:
        return _globals[name]
    for g in _PARENT_GLOBALS_LIST:
        if name in g and g[name] != default:
            return g[name]
    mod = sys.modules.get("record_session")
    if mod is not None and hasattr(mod, name):
        val = getattr(mod, name)
        if val != default:
            return val
    if _globals is not None and name in _globals:
        return _globals[name]
    return default


def main(argv=None, *, _globals: dict | None = None):
    attr = lambda name, default=None: _parent_attr(name, default, _globals)
    parser = argparse.ArgumentParser(
        description=attr("__doc__", __doc__) or __doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--caps", required=True, type=Path)
    parser.add_argument("--teleop-only", action="store_true")
    parser.add_argument("--body-only", action="store_true", help="manual body joints only; grippers remain passive")
    parser.add_argument("--task-card", type=Path, help="task design card to embed in session.json")
    parser.add_argument("--replay", type=Path, help="teach_trajectory.py output: a scripted teacher replaces the leader")
    parser.add_argument(
        "--chunks", type=Path, help="chunk library: chunk_runner.py holds the arm and takes judge commands"
    )
    parser.add_argument(
        "--params", type=Path, help="--chunks: cell-params.json for the runner (default: built-in values)"
    )
    parser.add_argument(
        "--io", type=Path, default=Path("chunk-io"), help="--chunks: command FIFO and status directory"
    )
    parser.add_argument("--operating-profile", type=Path, help="--chunks/--replay: per-device operating profile")
    parser.add_argument(
        "--arm", help="lock only this arm (its observer's instance name), so the other arm can work too"
    )
    args = parser.parse_args(argv)
    if args.operating_profile:
        if not (args.chunks or args.replay):
            parser.error("--operating-profile requires --chunks or --replay")
        args.operating_profile = args.operating_profile.expanduser().resolve()
    if args.body_only and not args.teleop_only:
        parser.error("--body-only requires --teleop-only")
    lc_fn = attr("load_caps", load_caps)
    mt_fn = attr("model_tuning", model_tuning)
    rt_fn = attr("robot_tuning", robot_tuning)
    caps = lc_fn(args.caps, model=mt_fn(), robot=rt_fn(args.operating_profile))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.task_card is not None:
        card = attr("load_task_card", load_task_card)(args.task_card)
        config = attr("compose", compose)(config, card, stamp=time.strftime("%Y%m%d-%H%M%S"))
        args.config = args.config.with_name(f"{args.config.stem}.{card['task_id']}.json")
        args.config.write_text(json.dumps(config, indent=2))
    if config["robot"]["type"] == "bi_omx_follower":
        ports = {
            arm + "." + role: config[section][arm]["port"]
            for arm in ("arm_a", "arm_b")
            for role, section in (("follower", "robot"), ("leader", "teleop"))
        }
    else:
        ports = {"follower": config["robot"]["port"], "leader": config["teleop"]["port"]}
    out = Path("session.jsonl")
    monitor_path = Path(f"motor-health-{time.time_ns()}.jsonl").absolute()
    monitor_state = Path(os.environ.get("ROSY_OMX_MONITOR_STATE", "motor-health-current.json")).absolute()
    monitor_owner = config["robot"]["id"]
    monitor_session = str(uuid4())

    def log(**row):
        row["t"] = round(time.time(), 3)
        with out.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(json.dumps(row, default=str), flush=True)

    def systemctl(verb, unit):
        sub = attr("subprocess", _std_subprocess)
        done = sub.run(["systemctl", "--user", verb, unit], capture_output=True, text=True, timeout=10)
        return done.stdout.strip()

    def run(command):
        sub = attr("subprocess", _std_subprocess)
        iopd = attr("interrupt_on_parent_death", interrupt_on_parent_death)
        ni = attr("no_interrupts", no_interrupts)
        child = sub.Popen(
            command,
            start_new_session=True,
            preexec_fn=iopd,
            env={
                **os.environ,
                "ROSY_OMX_MONITOR_LOG": str(monitor_path),
                "ROSY_OMX_MONITOR_STATE": str(monitor_state),
                "ROSY_OMX_MONITOR_OWNER": monitor_owner,
                "ROSY_OMX_MONITOR_SESSION": monitor_session,
            },
        )
        try:
            return child.wait()
        except KeyboardInterrupt:
            with ni():
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except sub.TimeoutExpired:
                    child.kill()
                    child.wait()
            raise

    attr("protect_signals", protect_signals)()
    replay = None
    if args.replay is not None:
        from teach_trajectory import load as load_trajectory

        replay = {**load_trajectory(args.replay, fps=config["dataset"]["fps"]), "path": str(args.replay.resolve())}
        plugins = str(Path(__file__).resolve().with_name("lerobot_plugins"))
        os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (plugins, os.environ.get("PYTHONPATH")) if p)
    chunks = None
    if args.chunks is not None:
        from chunk_runner import load_library

        load_library(args.chunks)
        chunks = {
            "library": str(args.chunks.resolve()),
            "io": str(args.io.resolve()),
            "sha256": hashlib.sha256(args.chunks.read_bytes()).hexdigest(),
            **({"params": str(args.params.resolve())} if args.params else {}),
            **({"load_model": os.environ["ROSY_LOAD_MODEL"]} if os.environ.get("ROSY_LOAD_MODEL") else {}),
        }
    import omx_incident

    bus_cls = attr("SerialBus", _DefaultSerialBus)
    sess_cls = attr("Session")
    session = sess_cls(
        open_bus=lambda which: bus_cls(ports[which], 0),
        systemctl=systemctl,
        run=run,
        log=log,
        replay=replay,
        chunks=chunks,
        operating_profile=args.operating_profile,
    )
    lock = attr("session_lock", session_lock)(args.arm)
    record = {}
    try:
        omx_incident.refuse_if_held(args.arm)
        record = session.execute(
            args.config, caps, teleop_only=args.teleop_only, task_card=args.task_card, body_only=args.body_only
        )
        if not args.teleop_only and chunks is None:
            try:
                se_fn = attr("static_episodes", static_episodes)
                record["static_episodes"] = se_fn(Path(config["dataset"]["root"]))
            except Exception as exc:
                record["static_episodes"] = f"error: {exc}"
    finally:
        try:
            try:
                from motor_health import finish_snapshot

                finish_snapshot(
                    monitor_state, monitor_owner, monitor_session, safe_end=bool(record.get("safe_end"))
                )
            except Exception as exc:
                record["motor_health_snapshot_error"] = str(exc)
            if record:
                record.update(
                    motor_health_log=str(monitor_path),
                    motor_health_log_created=monitor_path.is_file(),
                    motor_health_state=str(monitor_state),
                    motor_health_owner=monitor_owner,
                    motor_health_session=monitor_session,
                )
                Path("session.json").write_text(json.dumps(record, indent=2, default=str))
                try:
                    print(json.dumps(omx_incident.after_session(args.arm, ports.get("follower")), default=str)[:2000])
                except Exception as exc:
                    print(f"incident pipeline failed: {exc}")
        finally:
            lock.close()
    if not record.get("safe_end"):
        raise SystemExit("UNSAFE END: follower torque or caps not confirmed restored - see session.json")
    raise SystemExit(record.get("exit_code") or 0)
