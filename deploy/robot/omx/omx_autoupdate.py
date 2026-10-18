#!/usr/bin/env python3
"""Keep the OMX cell's native tools at the newest green main, switching only while the cell is idle.

Native (D-246): the device owners run on the host, so updates are release directories plus one
atomic `current` symlink, not containers. One run (a user systemd timer calls it every few minutes):

1. read the newest commit of the tracked branch (anonymous HTTPS for the public code repository);
2. wait until every required GitHub check of that commit completed successfully (`ci-result`);
3. unpack only the configured paths of that commit into `releases/<sha12>` and write `RELEASE`;
4. smoke-check the release (its tools import with the configured interpreter);
5. switch only when the cell is idle: no recording session holds `session.lock`, no process has the
   follower or leader serial device open, and every follower motor reports torque OFF; otherwise the
   prepared release waits for the next run;
6. move `current` atomically, re-run the smoke check through `current`, and roll back on failure;
7. keep the newest `keep` releases (always the current and previous ones).

Every step is one JSON line on stdout and the state is in `state.json`. Stopping updates:
`systemctl --user disable --now rosy-omx-autoupdate.timer`. Signing (D-441) is a later step.

  omx_autoupdate.py --config ~/.config/rosy/omx-autoupdate.json run [--dry-run]
  omx_autoupdate.py --config ... status | rollback
"""
from __future__ import annotations

import argparse
import fcntl
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
SMOKE = ("import sys; sys.path.insert(0, 'deploy/robot/omx'); "
         "import joint_tune, record_session, record_config; print('smoke ok')")


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
        return {run["name"]: (run["status"], run["conclusion"]) for run in runs}

    def archive(self, sha: str, paths, target: Path) -> None:
        mirror = Path(self.cfg["root"]) / "mirror.git"
        if not mirror.exists():
            subprocess.run(["git", "init", "--bare", "-q", str(mirror)], check=True)
        subprocess.run(["git", "-C", str(mirror), "fetch", "-q", "--depth", "1", self.cfg["repo_url"], sha],
                       check=True, timeout=600)
        data = subprocess.run(["git", "-C", str(mirror), "archive", "--format=tar", sha, *paths],
                              capture_output=True, check=True, timeout=600).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(target, filter="data")

    def smoke(self, release: Path) -> bool:
        done = subprocess.run([self.cfg["python"], "-c", SMOKE], cwd=release, capture_output=True, text=True,
                              timeout=120)
        return done.returncode == 0 and "smoke ok" in done.stdout

    def session_busy(self) -> bool:
        lock = Path(self.cfg["root"]) / "session.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
        return False

    def device_in_use(self) -> bool:
        for device in self.cfg["devices"]:
            resolved = os.path.realpath(device)
            if subprocess.run(["fuser", resolved], capture_output=True).returncode == 0:
                return True
        return False

    def follower_torque_off(self, release: Path) -> bool:
        code = ("import sys; sys.path.insert(0, 'deploy/robot/omx'); from joint_tune import SerialBus, FOLLOWER; "
                f"bus = SerialBus({self.cfg['devices'][0]!r}, 0)\n"
                "try:\n    on = []\n    for m in FOLLOWER:\n        bus.motor = m\n        on.append(bus.read('torque'))\n"
                "finally:\n    bus.close()\nprint('torque', sum(on))")
        done = subprocess.run([self.cfg["python"], "-c", code], cwd=release, capture_output=True, text=True,
                              timeout=60)
        return done.returncode == 0 and done.stdout.strip() == "torque 0"


class Updater:
    def __init__(self, cfg: dict, host) -> None:
        self.cfg, self.host = cfg, host
        self.root = Path(cfg["root"])
        self.releases = self.root / "releases"
        self.state_path = self.root / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return {"current": None, "previous": None, "history": []}

    def save(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)

    def link(self, name: str) -> None:
        tmp = self.root / "current.tmp"
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(Path("releases") / name)
        os.replace(tmp, self.root / "current")

    def idle(self, release: Path) -> str | None:
        if self.host.session_busy():
            return "session_running"
        if self.host.device_in_use():
            return "device_in_use"
        if not self.host.follower_torque_off(release):
            return "follower_torque_not_off"
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
        checks = self.host.checks(sha)
        for required in self.cfg["required_checks"]:
            status = checks.get(required)
            if status is None or status[0] != "completed":
                log(step="waiting_ci", release=name, check=required, status=status)
                return "waiting_ci"
            if status[1] != "success":
                log(step="ci_failed", release=name, check=required, status=status)
                return "ci_failed"
        release = self.releases / name
        if not release.exists():
            if dry_run:
                log(step="would_prepare", release=name)
                return "would_prepare"
            staging = self.releases / f"{name}.tmp"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            self.host.archive(sha, self.cfg["paths"], staging)
            (staging / "RELEASE").write_text(sha + "\n")
            if not self.host.smoke(staging):
                shutil.rmtree(staging, ignore_errors=True)
                state["failed"] = name
                self.save(state)
                log(step="smoke_failed", release=name)
                return "smoke_failed"
            os.replace(staging, release)
            log(step="prepared", release=name)
        busy = self.idle(release)
        if busy:
            log(step="deferred", release=name, reason=busy)
            return "deferred"
        if dry_run:
            log(step="would_switch", release=name)
            return "would_switch"
        previous = state["current"]
        self.link(name)
        if not self.host.smoke(self.root / "current"):
            if previous:
                self.link(previous)
            else:  # first install: leave no current pointing at a broken release
                (self.root / "current").unlink()
            log(step="rolled_back", release=name, to=previous)
            state["history"].append({"release": name, "result": "rolled_back", "at": time.time()})
            self.save(state)
            return "rolled_back"
        state.update(current=name, previous=previous)
        state["history"] = (state["history"] + [{"release": name, "result": "active", "at": time.time()}])[-50:]
        self.save(state)
        self.cleanup(state)
        log(step="switched", release=name, previous=previous)
        return "switched"

    def rollback(self) -> str:
        state = self.state()
        if not state["previous"]:
            return "no_previous"
        busy = self.idle(self.releases / state["previous"])
        if busy:
            log(step="deferred", reason=busy)
            return "deferred"
        self.link(state["previous"])
        state.update(current=state["previous"], previous=state["current"])
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


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("branch", "main")
    cfg.setdefault("required_checks", ["ci-result"])
    cfg.setdefault("paths", list(DEFAULT_PATHS))
    cfg.setdefault("keep", 3)
    cfg["root"] = os.path.expanduser(cfg.get("root", "~/rosy-omx"))
    missing = [k for k in ("repo_url", "github_repo", "python", "devices") if not cfg.get(k)]
    if missing or not cfg["required_checks"] or cfg["keep"] < 2:
        raise SystemExit(f"config needs {missing or 'required_checks and keep >= 2'}")
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
