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
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess  # noqa: F401  (re-exported for test monkeypatching)
import sys
import time  # noqa: F401  (re-exported for test monkeypatching)
import urllib.error

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

# Where the updater keeps its state; tools/remote/omx_hotfix.py writes floor_sha into the same file.
DEFAULT_CONFIG = "~/.config/rosy/omx-autoupdate.json"
DEFAULT_ROOT = "~/rosy-omx"
STATE_FILE = "state.json"
UPDATE_LOCK = "update.lock"


class Updater:
    def __init__(self, cfg: dict, host) -> None:
        self.cfg, self.host = cfg, host
        self.root = Path(cfg["root"])
        self.releases = self.root / "releases"
        self.envs = self.root / "envs"
        self.state_path = self.root / STATE_FILE

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
        if hasattr(self.host, "follower_idle_reason"):
            return self.host.follower_idle_reason(release, self.python(env))
        return None if self.host.follower_torque_off(release, self.python(env)) else "follower_torque_not_off"

    def trusted(self, sha: str, state: dict, *, release_verified: bool = False) -> str | None:
        if not release_verified:
            checks = self.host.checks(sha)
            for required in self.cfg["required_checks"]:
                status = checks.get(required)
                if status is None or status[0] != "completed":
                    return "waiting_ci"
                if status[1] != "success" or status[2] != "github-actions":
                    return "ci_failed"
        # floor_sha: the main commit under the last hand hotfix (omx_hotfix.py deploy); never go back below it
        if state.get("floor_sha") and not self.descends(state["floor_sha"], sha):
            return "below_hotfix_floor"
        if state.get("current_sha") and not self.descends(state["current_sha"], sha):
            return "not_descendant"
        if not release_verified and self.cfg.get("require_verified_commit") and not self.host.verified(sha):
            return "unverified_commit"
        return None

    def descends(self, base: str, head: str) -> bool:
        if base == head:
            return True
        try:
            return self.host.descends(base, head)
        except urllib.error.HTTPError as error:
            if error.code == 404:  # base not on origin yet (a floor from local main): refuse, do not fail the unit
                return False
            raise

    def run(self, *, dry_run: bool = False) -> str:
        self.releases.mkdir(parents=True, exist_ok=True)
        state = self.state()
        sha = self.host.remote_head()
        base_name = sha[:12]
        paths = _release_paths(self.cfg["paths"])
        cur = state.get("current")
        repaired = f"{base_name}-r1"
        repairing = cur == base_name and _incomplete_release(self.releases / cur, paths)
        if cur in (base_name, repaired) and not repairing:
            log(step="up_to_date", release=cur)
            return "up_to_date"
        name = repaired if repairing else base_name
        if name == state.get("failed"):
            log(step="known_bad", release=name)
            return "known_bad"
        release = self.releases / name
        already_verified = (
            release.is_dir()
            and (release / "RELEASE").is_file()
            and (release / "RELEASE").read_text(encoding="utf-8").strip() == sha
            and state.get("prepared_verified_sha") == sha
        )
        try:
            refused = self.trusted(sha, state, release_verified=already_verified)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                log(step="rate_limited", release=name, code=exc.code)
                return "rate_limited"
            raise
        if refused:
            log(step=refused, release=name)
            return refused
        if not release.exists():
            if dry_run:
                log(step="would_prepare", release=name)
                return "would_prepare"
            staging = self.releases / f"{name}.tmp"
            for leftover in self.releases.glob("*.tmp"):
                shutil.rmtree(leftover, ignore_errors=True)
            staging.mkdir()
            self.host.archive(sha, paths, staging)
            (staging / "RELEASE").write_text(sha + "\n")
            if self.cfg.get("lock", LOCK) and not (staging / self.cfg.get("lock", LOCK)).exists():
                shutil.rmtree(staging, ignore_errors=True)
                state["failed"] = name
                self.save(state)
                log(step="no_environment_lock", release=name)
                return "smoke_failed"
            env = self.env_for(staging)
            if not self._smoke_ok(staging, self.python(env)):
                shutil.rmtree(staging, ignore_errors=True)
                state["failed"] = name
                self.save(state)
                log(step="smoke_failed", release=name)
                return "smoke_failed"
            os.replace(staging, release)
            state["prepared_verified_sha"] = sha
            self.save(state)
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

    def _usable_release(self, name: str | None, env: str | None, paths: list[str]) -> bool:
        rel = self.releases / name if name else None
        return bool(rel and env and rel.is_dir() and self.python(env).exists() and not _incomplete_release(rel, paths))

    def _smoke_ok(self, release: Path, python: Path) -> bool:
        try:
            return bool(self.host.smoke(release, python))
        except (OSError, subprocess.SubprocessError):
            return False

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
        smoked = self._smoke_ok(self.root / "current", self.root / "current-env" / "bin" / "python")
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
        paths = _release_paths(self.cfg["paths"])
        if previous and _incomplete_release(self.releases / previous, paths):
            old_prev, old_env = state.get("previous"), state.get("previous_env")
            saved_prev, saved_env = (old_prev, old_env) if self._usable_release(old_prev, old_env, paths) else (None, None)
        else:
            saved_prev, saved_env = previous, previous_env
        state.update(current=name, previous=saved_prev, current_sha=sha, env=env, previous_env=saved_env)
        state["history"] = (state["history"] + [{"release": name, "result": "active", "at": time.time()}])[-50:]
        self.save(state)
        self.cleanup(state)
        log(step="switched", release=name, previous=saved_prev)
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
        prev, prev_env = state.get("previous"), state.get("previous_env")
        if not prev:
            return "no_previous"
        paths = _release_paths(self.cfg["paths"])
        prev_rel = self.releases / prev
        if not prev_rel.is_dir() or _incomplete_release(prev_rel, paths):
            log(step="rollback_refused", release=prev, reason="incomplete_previous")
            return "incomplete_previous"
        prev_py = self.python(prev_env) if prev_env else None
        if not prev_py or not prev_py.exists() or not self._smoke_ok(prev_rel, prev_py):
            log(step="rollback_refused", release=prev, reason="smoke_failed")
            return "smoke_failed"
        session = self.host.hold_session()
        if session is None:
            log(step="deferred", reason="session_running")
            return "deferred"
        try:
            busy = self.idle(prev_rel, prev_env)
            if busy:
                log(step="deferred", reason=busy)
                return "deferred"
            units = self.host.running(self.cfg.get("units", []))
            self.link(prev, prev_env)
            if self.cfg.get("idle_gate") != "cell":
                self.host.restart(units)
        finally:
            session.close()
        if self.cfg.get("idle_gate") == "cell":
            self.host.restart(units)
        cur_cur = state.get("current")
        cur_env = state.get("env")
        keep_cur = self._usable_release(cur_cur, cur_env, paths)
        state.update(current=prev, previous=cur_cur if keep_cur else None, env=prev_env, previous_env=cur_env if keep_cur else None, current_sha=None)
        self.save(state)
        log(step="rolled_back_manually", release=state["current"])
        return "rolled_back"

    def cleanup(self, state: dict) -> None:
        keep = {state["current"], state["previous"]}
        names = sorted((p for p in self.releases.iterdir() if p.is_dir() and not p.name.endswith(".tmp")), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in names[self.cfg["keep"] :]:
            if path.name not in keep:
                shutil.rmtree(path, ignore_errors=True)
        used = {state.get("env"), state.get("previous_env")}
        for path in self.envs.iterdir() if self.envs.exists() else ():
            if path.is_dir() and not path.name.endswith(".tmp") and path.name not in used:
                shutil.rmtree(path, ignore_errors=True)


def _release_paths(paths: list[str]) -> list[str]:
    out = list(paths)
    if "deploy/robot/omx" in out and "contracts/learning/src" not in out:
        out.append("contracts/learning/src")
    return out


def _incomplete_release(release: Path, paths: list[str]) -> bool:
    """True when an older updater archived deploy/robot/omx without contracts/learning/src."""
    return "deploy/robot/omx" in paths and (release / "deploy/robot/omx/cell_collect_plan.py").is_file() and not (release / "contracts/learning/src/rosy/contracts/learning/omx_collect_plan.py").is_file()


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("branch", "main")
    cfg.setdefault("required_checks", ["ci-result"])
    cfg["paths"] = _release_paths(cfg.get("paths", list(DEFAULT_PATHS)))
    cfg.setdefault("keep", 3)
    cfg["root"] = os.path.expanduser(cfg.get("root", DEFAULT_ROOT))
    if cfg.get("kind") == "service":
        missing = [k for k in ("repo_url", "github_repo", "base_python", "paths", "smoke", "units", "root") if not cfg.get(k)]
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
    parser.add_argument("--config", type=Path, default=Path(DEFAULT_CONFIG).expanduser())
    parser.add_argument("command", choices=("run", "status", "rollback"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    Path(cfg["root"]).mkdir(parents=True, exist_ok=True)
    with (Path(cfg["root"]) / UPDATE_LOCK).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        updater = Updater(cfg, Host(cfg))
        if args.command == "status":
            print(json.dumps(updater.state(), indent=2))
            return
        result = updater.run(dry_run=args.dry_run) if args.command == "run" else updater.rollback()
        sys.exit(0 if result not in {"ci_failed", "smoke_failed", "rolled_back", "incomplete_previous"} else 1)


if __name__ == "__main__":
    main()
