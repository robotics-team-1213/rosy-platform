#!/usr/bin/env python3
"""Spawn real parallel MuJoCo physics and ACT training workers publishing live to Rosy World."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

SIM_DIR = Path(__file__).resolve().parent
REPO = SIM_DIR.parents[1] if len(SIM_DIR.parents) > 1 and (SIM_DIR.parents[1] / "middleware").is_dir() else SIM_DIR
DEFAULT_MUJOCO_TASKS = ("stack", "rehandle", "outbound-stand")


def _common_world_args(args: argparse.Namespace) -> list[str]:
    flags: list[str] = []
    if args.world_url:
        flags.extend(["--world-url", args.world_url])
    if args.world_mdns_host:
        flags.extend(["--world-mdns-host", args.world_mdns_host, "--world-port", str(args.world_port)])
    if args.worlds_dir is not None:
        flags.extend(["--worlds-dir", str(args.worlds_dir)])
    if args.site_map_sha256:
        flags.extend(["--site-map-sha256", args.site_map_sha256])
    if args.world_token_env:
        flags.extend(["--world-token-env", args.world_token_env])
    return flags


def build_worker_specs(args: argparse.Namespace, *, repo_root: Path = REPO) -> list[dict[str, Any]]:
    """Build concrete subprocess commands for parallel MuJoCo and LeRobot ACT workers."""
    tasks = [t.strip() for t in args.mujoco_tasks.split(",") if t.strip()] or list(DEFAULT_MUJOCO_TASKS)
    world_flags = _common_world_args(args)
    out_root = Path(args.out).resolve()
    specs: list[dict[str, Any]] = []

    teacher_script = repo_root / "tools" / "sim" / "omx_two_arm_teacher.py"
    if not teacher_script.is_file():
        teacher_script = SIM_DIR / "omx_two_arm_teacher.py"
    mujoco_py = args.mujoco_python or sys.executable

    for idx in range(args.mujoco_workers):
        world_id = f"mujoco-ab-{idx + 1:02d}"
        task = tasks[idx % len(tasks)]
        worker_out = out_root / world_id
        cmd = [
            mujoco_py,
            str(teacher_script),
            "run",
            task,
            *(["--concurrent"] if getattr(args, "mujoco_concurrent", False) else []),
            "--seed",
            str(idx + 1),
            "--repeat",
            str(args.mujoco_repeat),
            "--episode",
            "1",
            "--out",
            str(worker_out),
            "--world-id",
            world_id,
            *world_flags,
        ]
        specs.append({"world_id": world_id, "kind": "mujoco", "task": task, "cmd": cmd, "out": worker_out})

    train_script = repo_root / "learning" / "training" / "omx" / "experiment_train.py"
    act_py = args.act_python or sys.executable
    for idx, req_path in enumerate(args.act_request):
        world_id = f"act-train-{idx + 1:02d}"
        worker_out = out_root / world_id / "run"
        cmd = [
            act_py,
            str(train_script),
            "--request",
            str(Path(req_path).resolve()),
            "--out",
            str(worker_out),
            "--world-id",
            world_id,
            *world_flags,
        ]
        specs.append({"world_id": world_id, "kind": "act", "request": str(req_path), "cmd": cmd, "out": worker_out})

    return specs


def _terminate_proc(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


def run_parallel(args: argparse.Namespace) -> dict[str, Any]:
    """Launch all configured workers concurrently, wait/monitor, and return structured summary."""
    specs = build_worker_specs(args)
    if not specs:
        raise ValueError("specify --mujoco-workers N and/or --act-request PATH")

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    logs_dir = out_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    popen_kwargs: dict[str, Any] = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    else:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    running: list[tuple[dict[str, Any], subprocess.Popen[Any], Any]] = []
    started = time.monotonic()
    timed_out = False

    def _shutdown_all(*_exc: object) -> None:
        for _spec, proc, _log in running:
            _terminate_proc(proc)

    prev_int = signal.signal(signal.SIGINT, lambda *_: (_shutdown_all(), sys.exit(130)))
    prev_term = signal.signal(signal.SIGTERM, lambda *_: (_shutdown_all(), sys.exit(143)))
    try:
        for spec in specs:
            Path(spec["out"]).parent.mkdir(parents=True, exist_ok=True)
            log_fh = (logs_dir / f"{spec['world_id']}.log").open("w", encoding="utf-8")
            proc = subprocess.Popen(
                spec["cmd"],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
            running.append((spec, proc, log_fh))

        while True:
            alive = [item for item in running if item[1].poll() is None]
            if not alive:
                break
            if args.timeout_s > 0 and (time.monotonic() - started) >= args.timeout_s:
                timed_out = True
                _shutdown_all()
                break
            time.sleep(0.2)
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        for _spec, proc, log_fh in running:
            _terminate_proc(proc)
            log_fh.close()

    results = []
    for spec, proc, _log_fh in running:
        results.append({
            "world_id": spec["world_id"],
            "kind": spec["kind"],
            "returncode": proc.returncode,
            "log": str(logs_dir / f"{spec['world_id']}.log"),
        })
    all_ok = (not timed_out) and all(r["returncode"] == 0 for r in results)
    return {
        "timed_out": timed_out,
        "elapsed_s": round(time.monotonic() - started, 2),
        "all_ok": all_ok,
        "workers": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="output root directory for parallel workers")
    parser.add_argument("--mujoco-workers", type=int, default=0, help="number of parallel OMX MuJoCo physics workers")
    parser.add_argument("--mujoco-tasks", default=",".join(DEFAULT_MUJOCO_TASKS), help="comma-separated teacher tasks")
    parser.add_argument("--mujoco-repeat", type=int, default=1, help="repeat episodes per MuJoCo worker")
    parser.add_argument("--mujoco-concurrent", action="store_true", help="pass --concurrent to omx_two_arm_teacher.py (only valid for zone-annotated plans)")
    parser.add_argument("--mujoco-python", help="Python interpreter with mujoco installed")
    parser.add_argument("--act-request", type=Path, action="append", default=[], help="experiment_train request JSON (repeatable)")
    parser.add_argument("--act-python", help="Python interpreter with lerobot/torch installed")
    parser.add_argument("--world-url", help="Rosy World HTTP base URL")
    parser.add_argument("--world-mdns-host", help="Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140, help="Rosy World port for --world-mdns-host")
    parser.add_argument("--worlds-dir", type=Path, help="optional directory for worlds/<world_id>.json")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--world-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    parser.add_argument("--timeout-s", type=float, default=0.0, help="optional batch timeout seconds (0 = wait)")
    args = parser.parse_args(argv)
    summary = run_parallel(args)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
