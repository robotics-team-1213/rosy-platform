#!/usr/bin/env python3
"""Keep the OMX cell's native tools at the newest green main, switching only while the cell is idle.

Native (D-246): the device owners run on the host, so updates are release directories plus one
atomic `current` symlink, not containers. One run (a user systemd timer calls it every few minutes):

1. read the newest commit of the tracked branch (anonymous HTTPS for the public code repository);
2. trust gate: every required check completed successfully and was reported by GitHub Actions; the
   commit descends from the installed one (a force-push back to old code is refused); optionally
   GitHub must show it as a verified signed commit (`require_verified_commit`);
3. unpack only the configured paths of that commit into `releases/<sha12>` and write `RELEASE`;
4. environment: one venv per sha256 of the release's `requirements-cell.lock` (`envs/<hash12>`),
   built with `base_python` before the idle gate and reused while the lock is unchanged; the release
   is smoke-checked with that venv (its tools import);
5. switch only when the cell is idle: no recording session holds `session.lock`, no process has the
   follower or leader serial device open, and every follower motor reports torque OFF; otherwise the
   prepared release waits for the next run. With `observers` ({unit, device, health} per follower),
   the active torque-OFF observer may be the bus's only owner and its fresh motor-health snapshot
   (within `observer_max_age_s`, default 10 s) is the torque evidence;
6. move `current` and `current-env` atomically, re-run the smoke check through them, and roll back on
   failure;
7. keep the newest `keep` releases and the venvs they use (always the current and previous ones).

`"kind": "service"` (D-805, e.g. the AI PC's rosy-situation) reuses the same steps for a host service:
`paths` and `smoke` come from the config, `lock` may be null (a `--system-site-packages` venv with
nothing installed), there is no cell to be idle, and after the switch the listed user `units` are
restarted and must stay active `settle` seconds, otherwise the previous release is linked and restarted.
Before each restart the `unit_files` (release paths) are copied from `current` into the user unit folder
and systemd reloads them, so a unit edit on main reaches the host and a rollback brings the old unit back.

A service may also need the idle cell (D-871: cameras, torque-OFF observers and the observation bridge):
`"idle_gate": "cell"` with the cell's `devices`, `follower_device` and/or `observers` holds the cell's
`session_lock` (default `~/rosy-omx/session.lock`) and switches only under the same idle rule as step 5.
The lock is released after the smoke check and before the restart, because the observer's own start
guard takes it. `"system_site_packages": true` builds the lock's venv over the host Python's packages
(the observers need the system ROS `rclpy`).

Every step is one JSON line on stdout and the state is in `state.json`. Stopping updates:
`systemctl --user disable --now rosy-omx-autoupdate.timer`. Release signing (D-441) remains a later step: until then trust rests on
branch protection of main, the Actions-reported checks and the ancestry rule.

  omx_autoupdate.py --config ~/.config/rosy/omx-autoupdate.json run [--dry-run]
  omx_autoupdate.py --config ... status | rollback
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

DEFAULT_PATHS = ("deploy/robot/omx", "contracts/foundation", "middleware/devices/omx/adapter",
                 "integrations/robots/omx", "learning/curation/omx", "test/test_omx_joint_tune.py",
                 "test/test_omx_record_session.py")
LOCK = "deploy/robot/omx/requirements-cell.lock"
SMOKE = ("import sys; sys.path.insert(0, 'deploy/robot/omx'); "
         "import joint_tune, record_session, record_config, omx_autoupdate; print('smoke ok')")


def log(**row):
    row["t"] = round(time.time(), 3)
    print(json.dumps(row, default=str), flush=True)


class Host:
    """Everything that touches git, GitHub, processes and devices; replaced by fakes in tests."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def remote_head(self) -> str:
        out = subprocess.run(["git", "ls-remote", self.cfg["repo_url"], f"refs/heads/{self.cfg['branch']}"],
                             capture_output=True, text=True, timeout=60, check=True).stdout.split()
        return out[0]

    def checks(self, sha: str) -> dict:
        url = f"https://api.github.com/repos/{self.cfg['github_repo']}/commits/{sha}/check-runs?per_page=100"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        runs = json.load(urllib.request.urlopen(request, timeout=30))["check_runs"]
        return {run["name"]: (run["status"], run["conclusion"], (run.get("app") or {}).get("slug"))
                for run in runs}

    def _api(self, path: str) -> dict:
        request = urllib.request.Request(f"https://api.github.com/repos/{self.cfg['github_repo']}/{path}",
                                         headers={"Accept": "application/vnd.github+json"})
        return json.load(urllib.request.urlopen(request, timeout=30))

    def descends(self, base: str, head: str) -> bool:
        return self._api(f"compare/{base}...{head}")["status"] in {"ahead", "identical"}

    def verified(self, sha: str) -> bool:
        return bool(self._api(f"commits/{sha}")["commit"]["verification"]["verified"])

    def build_env(self, lock: Path | None, target: Path) -> None:
        if lock is None:  # a service on the host's own packages
            subprocess.run([self.cfg["base_python"], "-m", "venv", "--system-site-packages", str(target)],
                           check=True, timeout=300)
            return
        system = ["--system-site-packages"] if self.cfg.get("system_site_packages") else []
        subprocess.run([self.cfg["base_python"], "-m", "venv", *system, str(target)], check=True, timeout=300)
        subprocess.run([str(target / "bin" / "python"), "-m", "pip", "install", "--no-input", "-q", "-r", str(lock)],
                       check=True, timeout=3000)

    def running(self, units) -> list:
        """The units to restart: all, or with `restart_running_only` the active ones, so a unit stopped by
        hand (an observer stopped for the real owner) stays stopped."""
        if not self.cfg.get("restart_running_only"):
            return list(units)
        return [u for u in units
                if subprocess.run(["systemctl", "--user", "is-active", "--quiet", u], timeout=30).returncode == 0]

    def restart(self, units) -> bool:
        """Restart the service units and report whether all are still active after `settle` seconds."""
        complete = True
        try:
            if self.cfg.get("unit_files"):  # the live release's own unit files, so unit edits on main arrive too
                unit_dir = Path(self.cfg.get("unit_dir", "~/.config/systemd/user")).expanduser()
                for name in self.cfg["unit_files"]:
                    try:
                        shutil.copyfile(Path(self.cfg["root"]) / "current" / name, unit_dir / Path(name).name)
                    except OSError:  # an older release (rollback target) may lack one: keep going, still restart
                        complete = False
                        log(step="unit_file_missing", file=name)
                try:
                    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=60)
                except subprocess.SubprocessError:  # still restart on what systemd has
                    complete = False
            if not units:
                return complete
            if subprocess.run(["systemctl", "--user", "restart", *units], timeout=120).returncode != 0:
                return False
            time.sleep(self.cfg.get("settle", 10))
            active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", *units], timeout=30)
            return complete and active.returncode == 0  # forward: a release missing its unit file fails
        except (OSError, subprocess.SubprocessError):  # systemctl missing or timed out
            return False

    def archive(self, sha: str, paths, target: Path) -> None:
        mirror = Path(self.cfg["root"]) / "mirror.git"
        if not mirror.exists():
            subprocess.run(["git", "init", "--bare", "-q", str(mirror)], check=True)
        # main() holds update.lock, so no other git process uses this mirror: a lock here is left by a
        # fetch that was killed (AI PC 10-20: shallow.lock blocked every run for three days).
        for stale in mirror.glob("*.lock"):
            stale.unlink()
        subprocess.run(["git", "-C", str(mirror), "fetch", "-q", "--depth", "1", self.cfg["repo_url"], sha],
                       check=True, timeout=600)
        data = subprocess.run(["git", "-C", str(mirror), "archive", "--format=tar", sha, *paths],
                              capture_output=True, check=True, timeout=600).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(target, filter="data")

    def smoke(self, release: Path, python: Path) -> bool:
        done = subprocess.run([str(python), "-c", self.cfg.get("smoke", SMOKE)], cwd=release, capture_output=True,
                              text=True, timeout=120)
        return done.returncode == 0 and "smoke ok" in done.stdout

    def hold_session(self):
        """Take the cell's session lock (the one joint_tune and record_session hold) and keep it for the
        whole switch, so no session can start between the idle check and the smoke check."""
        lock = Path(self.cfg.get("session_lock") or Path(self.cfg["root"]) / "session.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        handle = lock.open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        return handle

    def _observer_pid(self, unit: str) -> str | None:
        shown = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "MainPID"],
                               capture_output=True, text=True, timeout=10).stdout
        props = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
        return props["MainPID"] if props.get("ActiveState") == "active" and props.get("MainPID", "0") != "0" else None

    def device_in_use(self) -> bool:
        # A configured torque-OFF observer may hold its follower bus permanently; any other owner is a session.
        observed = {os.path.realpath(o["device"]): o["unit"] for o in self.cfg.get("observers", [])}
        for device in self.cfg["devices"]:
            resolved = os.path.realpath(device)
            found = subprocess.run(["fuser", resolved], capture_output=True, text=True)
            if found.returncode == 0:
                owners = found.stdout.split()
                if resolved not in observed or owners != [self._observer_pid(observed[resolved])]:
                    return True
        return False

    def follower_torque_off(self, release: Path, python: Path) -> bool:
        observers = self.cfg.get("observers")
        if observers:
            return all(self._observed_torque_off(o) for o in observers)
        code = ("import sys; sys.path.insert(0, 'deploy/robot/omx'); from joint_tune import SerialBus, FOLLOWER; "
                f"bus = SerialBus({self.cfg['follower_device']!r}, 0)\n"
                "try:\n    on = []\n    for m in FOLLOWER:\n        bus.motor = m\n        on.append(bus.read('torque'))\n"
                "finally:\n    bus.close()\nprint('torque', sum(on))")
        done = subprocess.run([str(python), "-c", code], cwd=release, capture_output=True, text=True,
                              timeout=60)
        return done.returncode == 0 and done.stdout.strip() == "torque 0"

    def _observed_torque_off(self, observer: dict) -> bool:
        """The observer's own fresh motor-health snapshot: every expected motor reports torque OFF."""
        try:
            health = json.loads(Path(observer["health"]).read_text(encoding="utf-8"))
            motors = health["motors"]
            fresh = time.time() - float(health["observed_at"]) <= float(self.cfg.get("observer_max_age_s", 10))
            return (fresh and isinstance(motors, list) and len(motors) == health["expected_motor_count"] > 0
                    and all(m.get("torque_enabled") is False for m in motors))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def follower_missing(self) -> bool:
        return not self.cfg.get("observers") and not os.path.exists(self.cfg["follower_device"])


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
            log(step="env_built", env=name)
        return name

    def python(self, env: str) -> Path:
        return self.envs / env / "bin" / "python"

    def idle(self, release: Path, env: str) -> str | None:
        if self.cfg.get("kind") == "service" and self.cfg.get("idle_gate") != "cell":
            # no cell; the restart and its health check guard the switch
            return None
        if self.host.device_in_use():
            return "device_in_use"
        if getattr(self.host, "follower_missing", lambda: False)():
            return "follower_device_missing"  # a replaced board, not a powered arm: fix follower_device
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
        if name == state.get("failed"):  # do not refetch a release that failed until main moves on
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
            for leftover in self.releases.glob("*.tmp"):  # failed preparations of this or older releases
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
        # A first install may replace a hand-made `current` (deploy-situation.sh); put it back on failure.
        before = {link: os.readlink(self.root / link) for link in ("current", "current-env")
                  if (self.root / link).is_symlink()}
        self.link(name, env)
        units = self.host.running(self.cfg.get("units", []))  # once: the rollback restarts the same ones
        smoked = self.host.smoke(self.root / "current", self.root / "current-env" / "bin" / "python")
        # rosy-omx-observer@ refuses to start while anyone holds the cell lock, this updater included
        session.close()
        if not (smoked and self.host.restart(units)):
            if previous:
                self.link(previous, previous_env)
            else:  # first install: what was there before, or no current pointing at a broken release
                self.unlink()
                for link, target in before.items():
                    (self.root / link).symlink_to(target)
            self.host.restart(units)
            log(step="rolled_back", release=name, to=previous)
            state["failed"] = name  # do not retry it every run until main moves on
            state["history"].append({"release": name, "result": "rolled_back", "at": time.time()})
            self.save(state)
            return "rolled_back"
        state.update(current=name, previous=previous, current_sha=sha, env=env, previous_env=previous_env)
        state["history"] = (state["history"] + [{"release": name, "result": "active", "at": time.time()}])[-50:]
        self.save(state)
        self.cleanup(state)
        log(step="switched", release=name, previous=previous)
        return "switched"

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
        finally:
            session.close()
        self.host.restart(units)
        # current_sha is dropped: after a manual rollback the next forward update is not refused as older
        state.update(current=state["previous"], previous=state["current"], env=state["previous_env"],
                     previous_env=state["env"], current_sha=None)
        self.save(state)
        log(step="rolled_back_manually", release=state["current"])
        return "rolled_back"

    def cleanup(self, state: dict) -> None:
        keep = {state["current"], state["previous"]}
        names = sorted((p for p in self.releases.iterdir() if p.is_dir() and not p.name.endswith(".tmp")),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in names[self.cfg["keep"]:]:
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
    if cfg.get("kind") == "service":  # its own paths, smoke and root; never the cell's session lock
        missing = [k for k in ("repo_url", "github_repo", "base_python", "paths", "smoke", "units", "root")
                   if not cfg.get(k)]
        cfg.setdefault("lock", None)
        if cfg.get("idle_gate") == "cell":  # the cell's own lock and idle evidence, not this root's
            missing += [k for k in ("devices",) if not cfg.get(k)]
            if not cfg.get("observers") and not cfg.get("follower_device"):
                missing.append("observers or follower_device")
            sessions = os.environ.get("ROSY_OMX_HOME") or os.path.join(os.path.expanduser("~"), "rosy-omx")
            cfg.setdefault("session_lock", os.path.join(os.path.expanduser(sessions), "session.lock"))
        elif cfg.get("idle_gate") is not None:
            raise SystemExit("idle_gate must be \"cell\" or absent")
        if missing or not cfg["required_checks"] or cfg["keep"] < 2:
            raise SystemExit(f"config needs {missing or 'required_checks and keep >= 2'}")
        return cfg
    missing = [k for k in ("repo_url", "github_repo", "base_python", "devices", "follower_device") if not cfg.get(k)]
    if missing or not cfg["required_checks"] or cfg["keep"] < 2:
        raise SystemExit(f"config needs {missing or 'required_checks and keep >= 2'}")
    sessions = os.environ.get("ROSY_OMX_HOME") or os.path.join(os.path.expanduser("~"), "rosy-omx")
    if os.path.realpath(os.path.expanduser(sessions)) != os.path.realpath(cfg["root"]):  # == joint_tune.lock_root()
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
        fcntl.flock(lock, fcntl.LOCK_EX)  # one updater at a time
        updater = Updater(cfg, Host(cfg))
        if args.command == "status":
            print(json.dumps(updater.state(), indent=2))
            return
        result = updater.run(dry_run=args.dry_run) if args.command == "run" else updater.rollback()
        sys.exit(0 if result not in {"ci_failed", "smoke_failed", "rolled_back"} else 1)


if __name__ == "__main__":
    main()
