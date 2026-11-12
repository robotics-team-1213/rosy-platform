#!/usr/bin/env python3
"""Keep the OMX cell's native tools at the newest green main, switching only while the cell is idle.

Single Responsibility:
  - Atomic Release State Machine & Rollback Controller (`Updater`), configuration validator (`load_config`),
    and CLI entrypoint (`main`).
  - Host Git/GitHub/Venv/Systemd/Bus I/O Adapter (`Host`, `DEFAULT_PATHS`, `LOCK`, `SMOKE`, `log`)
    lives in `omx_autoupdate_host.py` and is re-exported here for backward compatibility.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess  # noqa: F401  (re-exported for test monkeypatching)
import sys
import time  # noqa: F401  (re-exported for test monkeypatching)

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from omx_autoupdate_host import (  # noqa: E402,F401  (re-exported)
    DEFAULT_PATHS,
    LOCK,
    SMOKE,
    Host,
    log,
)


class Updater:
    def __init__(self, cfg: dict, host) -> None:
        self.cfg, self.host = cfg, host
        self.root = Path(cfg["root"])
        self.releases = self.root / "releases"
        self.envs = self.root / "envs"
        self.state_path = self.root / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return {"current": None, "previous": None, "history": []}
        except ValueError:  # a corrupt state file: keep it aside and trust the links on disk
            os.replace(self.state_path, self.state_path.with_suffix(f".corrupt-{int(time.time())}"))
            current = self.root / "current"
            name = Path(os.readlink(current)).name if current.is_symlink() else None
            env = Path(os.readlink(self.root / "current-env")).name if (self.root / "current-env").is_symlink() else None
            log(step="state_rebuilt", current=name)
            return {"current": name, "previous": None, "env": env, "history": []}

    def save(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)

    def link(self, name: str, env: str) -> None:
        for link, target in (("current-env", Path("envs") / env), ("current", Path("releases") / name)):
            tmp = self.root / f"{link}.tmp"
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            tmp.symlink_to(target)
            os.replace(tmp, self.root / link)

    def unlink(self) -> None:
        for link in ("current", "current-env"):
            if (self.root / link).is_symlink():
                (self.root / link).unlink()

    def env_for(self, release: Path) -> str:
        """The venv for this release's lock, built once per lock hash."""
        rel = self.cfg.get("lock", LOCK)
        lock = release / rel if rel else None
        name = hashlib.sha256(lock.read_bytes() if lock else b"system-site-packages").hexdigest()[:12]
        target = self.envs / name
        if not target.exists():
            staging = self.envs / f"{name}.tmp"
            shutil.rmtree(staging, ignore_errors=True)
            self.envs.mkdir(parents=True, exist_ok=True)
            self.host.build_env(lock, staging)
            os.replace(staging, target)
            old, new = str(staging).encode(), str(target).encode()
            for script in (target / "bin").iterdir():
                if script.is_file() and not script.is_symlink() and old in (data := script.read_bytes()):
                    script.write_bytes(data.replace(old, new))
            log(step="env_built", env=name)
        return name

    def python(self, env: str) -> Path:
        return self.envs / env / "bin" / "python"

    def idle(self, release: Path, env: str) -> str | None:
        if self.cfg.get("kind") == "service" and self.cfg.get("idle_gate") != "cell":
            return None
        if self.host.device_in_use():
            return "device_in_use"
        if getattr(self.host, "follower_missing", lambda: False)():
            return "follower_device_missing"
        if not self.host.follower_torque_off(release, self.python(env)):
            return "follower_torque_not_off"
        return None

    def trusted(self, sha: str, state: dict) -> str | None:
        checks = self.host.checks(sha)
        for required in self.cfg["required_checks"]:
            status = checks.get(required)
            if status is None or status[0] != "completed":
                return "waiting_ci"
            if status[1] != "success" or status[2] != "github-actions":
                return "ci_failed"
        if state.get("current_sha") and not self.host.descends(state["current_sha"], sha):
            return "not_descendant"
        if self.cfg.get("require_verified_commit") and not self.host.verified(sha):
            return "unverified_commit"
        return None

    def run(self, *, dry_run: bool = False) -> str:
        self.releases.mkdir(parents=True, exist_ok=True)
        state = self.state()
        sha = self.host.remote_head()
        name = sha[:12]
        if name == state["current"]:
            log(step="up_to_date", release=name)
            return "up_to_date"
        if name == state.get("failed"):
            log(step="known_bad", release=name)
            return "known_bad"
        refused = self.trusted(sha, state)
        if refused:
            log(step=refused, release=name)
            return refused
        release = self.releases / name
        if not release.exists():
            if dry_run:
                log(step="would_prepare", release=name)
                return "would_prepare"
            staging = self.releases / f"{name}.tmp"
            for leftover in self.releases.glob("*.tmp"):
                shutil.rmtree(leftover, ignore_errors=True)
            staging.mkdir()
            self.host.archive(sha, self.cfg["paths"], staging)
            (staging / "RELEASE").write_text(sha + "\n")
            if self.cfg.get("lock", LOCK) and not (staging / self.cfg.get("lock", LOCK)).exists():
                shutil.rmtree(staging, ignore_errors=True)
                state["failed"] = name
                self.save(state)
                log(step="no_environment_lock", release=name)
                return "smoke_failed"
            env = self.env_for(staging)
            if not self.host.smoke(staging, self.python(env)):
                shutil.rmtree(staging, ignore_errors=True)
                state["failed"] = name
                self.save(state)
                log(step="smoke_failed", release=name)
                return "smoke_failed"
            os.replace(staging, release)
            log(step="prepared", release=name)
        env = self.env_for(release)
        session = self.host.hold_session()
        if session is None:
            log(step="deferred", release=name, reason="session_running")
            return "deferred"
        try:
            return self.switch(state, sha, name, release, env, dry_run, session)
        finally:
            session.close()

    def switch(self, state, sha, name, release, env, dry_run, session) -> str:
        busy = self.idle(release, env)
        if busy:
            log(step="deferred", release=name, reason=busy)
            return "deferred"
        if dry_run:
            log(step="would_switch", release=name)
            return "would_switch"
        previous, previous_env = state["current"], state.get("env")
        before = {
            link: os.readlink(self.root / link)
            for link in ("current", "current-env")
            if (self.root / link).is_symlink()
        }
        self.link(name, env)
        smoked = self.host.smoke(self.root / "current", self.root / "current-env" / "bin" / "python")
        if not smoked:
            self.relink(previous, previous_env, before)
        units = self.host.running(self.cfg.get("units", []))
        released = self.cfg.get("idle_gate") == "cell"
        if released:
            session.close()
        if not (smoked and self.host.restart(units)):
            if smoked:
                self.relink(previous, previous_env, before)
            self.host.restart(units)
            log(step="rolled_back", release=name, to=previous)
            retaken = self.host.hold_session() if released and smoked else True
            if retaken is None:
                log(step="deferred", release=name, reason="session_started_during_restart")
                return "deferred"
            if released and smoked:
                retaken.close()
            state["failed"] = name
            state["history"].append({"release": name, "result": "rolled_back", "at": time.time()})
            self.save(state)
            return "rolled_back"
        state.update(current=name, previous=previous, current_sha=sha, env=env, previous_env=previous_env)
        state["history"] = (state["history"] + [{"release": name, "result": "active", "at": time.time()}])[-50:]
        self.save(state)
        self.cleanup(state)
        log(step="switched", release=name, previous=previous)
        return "switched"

    def relink(self, previous, previous_env, before) -> None:
        if previous:
            self.link(previous, previous_env)
        else:
            self.unlink()
            for link, target in before.items():
                (self.root / link).symlink_to(target)

    def rollback(self) -> str:
        state = self.state()
        if not state["previous"]:
            return "no_previous"
        session = self.host.hold_session()
        if session is None:
            log(step="deferred", reason="session_running")
            return "deferred"
        try:
            busy = self.idle(self.releases / state["previous"], state["previous_env"])
            if busy:
                log(step="deferred", reason=busy)
                return "deferred"
            units = self.host.running(self.cfg.get("units", []))
            self.link(state["previous"], state["previous_env"])
            if self.cfg.get("idle_gate") != "cell":
                self.host.restart(units)
        finally:
            session.close()
        if self.cfg.get("idle_gate") == "cell":
            self.host.restart(units)
        state.update(
            current=state["previous"],
            previous=state["current"],
            env=state["previous_env"],
            previous_env=state["env"],
            current_sha=None,
        )
        self.save(state)
        log(step="rolled_back_manually", release=state["current"])
        return "rolled_back"

    def cleanup(self, state: dict) -> None:
        keep = {state["current"], state["previous"]}
        names = sorted(
            (p for p in self.releases.iterdir() if p.is_dir() and not p.name.endswith(".tmp")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in names[self.cfg["keep"] :]:
            if path.name not in keep:
                shutil.rmtree(path, ignore_errors=True)
        used = {state.get("env"), state.get("previous_env")}
        for path in self.envs.iterdir() if self.envs.exists() else ():
            if path.is_dir() and not path.name.endswith(".tmp") and path.name not in used:
                shutil.rmtree(path, ignore_errors=True)


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("branch", "main")
    cfg.setdefault("required_checks", ["ci-result"])
    cfg.setdefault("paths", list(DEFAULT_PATHS))
    cfg.setdefault("keep", 3)
    cfg["root"] = os.path.expanduser(cfg.get("root", "~/rosy-omx"))
    if cfg.get("kind") == "service":
        missing = [
            k
            for k in ("repo_url", "github_repo", "base_python", "paths", "smoke", "units", "root")
            if not cfg.get(k)
        ]
        cfg.setdefault("lock", None)
        if cfg.get("idle_gate") == "cell":
            missing += [k for k in ("devices",) if not cfg.get(k)]
            if not cfg.get("observers") and not cfg.get("follower_device"):
                missing.append("observers or follower_device")
            sessions = os.environ.get("ROSY_OMX_HOME") or os.path.join(os.path.expanduser("~"), "rosy-omx")
            cfg.setdefault("session_lock", os.path.join(os.path.expanduser(sessions), "session.lock"))
        elif cfg.get("idle_gate") is not None:
            raise SystemExit('idle_gate must be "cell" or absent')
        if missing or not cfg["required_checks"] or cfg["keep"] < 2:
            raise SystemExit(f"config needs {missing or 'required_checks and keep >= 2'}")
        return cfg
    missing = [k for k in ("repo_url", "github_repo", "base_python", "devices", "follower_device") if not cfg.get(k)]
    if missing or not cfg["required_checks"] or cfg["keep"] < 2:
        raise SystemExit(f"config needs {missing or 'required_checks and keep >= 2'}")
    sessions = os.environ.get("ROSY_OMX_HOME") or os.path.join(os.path.expanduser("~"), "rosy-omx")
    if os.path.realpath(os.path.expanduser(sessions)) != os.path.realpath(cfg["root"]):
        raise SystemExit(f"root must be {sessions}, where joint_tune and record_session take session.lock")
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("~/.config/rosy/omx-autoupdate.json").expanduser())
    parser.add_argument("command", choices=("run", "status", "rollback"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    Path(cfg["root"]).mkdir(parents=True, exist_ok=True)
    with (Path(cfg["root"]) / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        updater = Updater(cfg, Host(cfg))
        if args.command == "status":
            print(json.dumps(updater.state(), indent=2))
            return
        result = updater.run(dry_run=args.dry_run) if args.command == "run" else updater.rollback()
        sys.exit(0 if result not in {"ci_failed", "smoke_failed", "rolled_back"} else 1)


if __name__ == "__main__":
    main()
