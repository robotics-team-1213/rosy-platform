"""rosy-release host CLI. Automatic checks never call install or rollback."""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error

from bundle import BundleError, release_id, stage_archive
from delivery import Delivery
from github_release import download, latest
from layout import ActivationUnreadable, Layout, read_activation, write_json_atomic
from release_runtime import DockerRuntime
from signing import SigningToolMissing
from updater import RecoveryHeld, Updater


@contextlib.contextmanager
def release_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BundleError("UPDATE_BUSY", "another release operation is in progress") from exc
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def configuration(layout):
    path = layout.etc / "updates.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"repository", "signing_key_id", "os_suite"}:
        raise BundleError("UPDATE_CONFIG", "unexpected update configuration fields")
    key = data.get("signing_key_id")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", key):
        raise BundleError("UPDATE_CONFIG", "configure the preinstalled signing_key_id")
    if data.get("os_suite") not in {"bookworm", "trixie"}:
        raise BundleError("UPDATE_CONFIG", "configure the commissioned device OS suite")
    return data


def updater_for(layout, runtime):
    return Updater(layout, stop_runtime=runtime.stop, start_runtime=runtime.start, health_check=runtime.healthy)


def execute(args):
    layout = Layout.rooted(Path(args.root).resolve()) if args.root else Layout.default()
    if args.command == "install":
        release_id(args.release_id)
    runtime = DockerRuntime(layout)
    updater = updater_for(layout, runtime)
    if args.command == "status":
        current = read_activation(layout) if layout.activation.exists() else None
        return {"ok": True, "activation": asdict(current) if current else None,
                "state": updater.read_state(), "recovery_hold": updater.read_recovery_hold(),
                "staged": sorted(p.name for p in layout.staging.glob("*")
                                 if p.is_dir() and not p.name.startswith("."))}
    if not args.root and (os.name != "posix" or os.geteuid() != 0):
        raise BundleError("ROOT_REQUIRED", "mutating host release commands require root")
    with release_lock(layout.etc / "release.lock"):
        if args.command == "runtime":
            if args.action == "up" and layout.journal.exists():
                raise BundleError("RECOVERY_REQUIRED", "recover the pending activation before starting runtime")
            runtime.start("core") if args.action == "up" else runtime.stop()
            return {"ok": True, "code": "CORE_STARTED" if args.action == "up" else "RUNTIME_STOPPED"}
        if args.command == "recover":
            outcome = updater.recover()
            return {"ok": not outcome.blocks_runtime, "code": outcome.state.value,
                    "release_id": outcome.release_id, "detail": outcome.detail}
        if args.command == "clear-hold":
            runtime.assert_stopped()
            updater.clear_recovery_hold()
            return {"ok": True, "code": "HOLD_CLEARED"}
        config = configuration(layout)
        key = layout.trusted_keys / f"{config['signing_key_id']}.pem"
        target = {"board": "raspberry-pi-5", "architecture": "arm64",
                  "os_family": "raspberry-pi-os-lite", "os_suite": config["os_suite"]}
        delivery = Delivery(layout, key, runtime, device_target=target)
        if args.command == "stage":
            version = delivery.stage(Path(args.bundle))
            return {"ok": True, "code": "STAGED", "release_id": version}
        if args.command == "check":
            current = delivery.current()
            candidate = latest(config.get("repository"), current.release_id if current else None)
            result = {"ok": True, "code": "UPDATE_AVAILABLE" if candidate else "NO_NEW_RELEASE",
                      "release_id": candidate.release_id if candidate else None}
            if candidate and args.download:
                path = download(candidate, layout.cache / "downloads")
                staged = stage_archive(path, layout, key, device_target=target)
                if staged.name != candidate.release_id:
                    raise BundleError("RELEASE_ID_MISMATCH", "GitHub tag differs from signed bundle")
                result["code"] = "STAGED"
            write_json_atomic(layout.etc / "update-check.json", result)
            return result
        outcome = delivery.install(args.release_id) if args.command == "install" else delivery.rollback()
        return {"ok": outcome.state.value == "ACTIVATED_CORE_ONLY", "code": outcome.state.value,
                "release_id": outcome.release_id, "detail": outcome.detail}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="isolated root for rehearsal; never the live device root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "stage", "check", "install", "rollback", "recover", "clear-hold", "runtime"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true", help="emit machine-readable result (default)")
        if name == "stage":
            command.add_argument("bundle")
        elif name == "check":
            command.add_argument("--download", action="store_true", help="download and verify; never install")
        elif name == "install":
            command.add_argument("--release-id", required=True)
        elif name == "runtime":
            command.add_argument("action", choices=("up", "down"))
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except BundleError as exc:
        result = {"ok": False, "code": exc.code, "detail": exc.detail}
    except (OSError, ValueError, KeyError, TypeError, ActivationUnreadable, RecoveryHeld,
            SigningToolMissing, subprocess.SubprocessError, urllib.error.URLError) as exc:
        # Do not echo configuration contents, URLs, credentials or command stderr.
        result = {"ok": False, "code": "RELEASE_OPERATION_FAILED", "detail": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
