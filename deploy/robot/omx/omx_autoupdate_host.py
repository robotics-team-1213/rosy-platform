#!/usr/bin/env python3
"""Host I/O Adapter for OMX Auto-Updater (`omx_autoupdate_host.py`).

Single Responsibility:
  - Encapsulates all external host interactions (`Host`): Git `ls-remote`/`archive`,
    GitHub Check-Runs/compare/signature API, virtualenv creation (`venv`/`uv`),
    user `systemctl` daemon-reload/restart/is-active, `session.lock` acquisition,
    and serial device / observer torque-OFF readiness checks.
"""
from __future__ import annotations

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

DEFAULT_PATHS = (
    "deploy/robot/omx",
    "contracts/foundation",
    "middleware/devices/omx/adapter",
    "operations/overhead/rosy_vision",  # omx_incident's Fleet link (D-971)
    "integrations/robots/omx",
    "learning/curation/omx",
    "test/test_omx_joint_tune.py",
    "test/test_omx_record_session.py",
)
LOCK = "deploy/robot/omx/requirements-cell.lock"
SMOKE = (
    "import sys; sys.path.insert(0, 'deploy/robot/omx'); "
    "import joint_tune, record_session, record_config, omx_autoupdate; print('smoke ok')"
)


def _sp():
    mod = sys.modules.get("omx_autoupdate")
    return getattr(mod, "subprocess", subprocess) if mod is not None else subprocess


def _tm():
    mod = sys.modules.get("omx_autoupdate")
    return getattr(mod, "time", time) if mod is not None else time


def log(**row):
    row["t"] = round(_tm().time(), 3)
    print(json.dumps(row, default=str), flush=True)


class Host:
    """Everything that touches git, GitHub, processes and devices; replaced by fakes in tests."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def remote_head(self) -> str:
        out = _sp().run(
            ["git", "ls-remote", self.cfg["repo_url"], f"refs/heads/{self.cfg['branch']}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.split()
        return out[0]

    def checks(self, sha: str) -> dict:
        url = f"https://api.github.com/repos/{self.cfg['github_repo']}/commits/{sha}/check-runs?per_page=100"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        runs = json.load(urllib.request.urlopen(request, timeout=30))["check_runs"]
        return {
            run["name"]: (run["status"], run["conclusion"], (run.get("app") or {}).get("slug")) for run in runs
        }

    def _api(self, path: str) -> dict:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.cfg['github_repo']}/{path}",
            headers={"Accept": "application/vnd.github+json"},
        )
        return json.load(urllib.request.urlopen(request, timeout=30))

    def descends(self, base: str, head: str) -> bool:
        return self._api(f"compare/{base}...{head}")["status"] in {"ahead", "identical"}

    def verified(self, sha: str) -> bool:
        return bool(self._api(f"commits/{sha}")["commit"]["verification"]["verified"])

    def build_env(self, lock: Path | None, target: Path) -> None:
        sp = _sp()
        if lock is None:  # a service on the host's own packages
            make = (
                [os.path.expanduser(self.cfg["uv"]), "venv", "-q", "--python", self.cfg["base_python"]]
                if self.cfg.get("uv")
                else [self.cfg["base_python"], "-m", "venv"]
            )
            sp.run([*make, "--system-site-packages", str(target)], check=True, timeout=300)
            return
        system = ["--system-site-packages"] if self.cfg.get("system_site_packages") else []
        if self.cfg.get("uv"):  # the Fleet PC's system Python 3.14 has no ensurepip (python3-venv), 2026-10-25
            sp.run(
                [
                    os.path.expanduser(self.cfg["uv"]),
                    "venv",
                    "-q",
                    "--python",
                    self.cfg["base_python"],
                    *system,
                    str(target),
                ],
                check=True,
                timeout=300,
            )
            sp.run(
                [
                    os.path.expanduser(self.cfg["uv"]),
                    "pip",
                    "install",
                    "-q",
                    "--python",
                    str(target / "bin" / "python"),
                    "-r",
                    str(lock),
                ],
                check=True,
                timeout=3000,
            )
            return
        sp.run([self.cfg["base_python"], "-m", "venv", *system, str(target)], check=True, timeout=300)
        sp.run(
            [str(target / "bin" / "python"), "-m", "pip", "install", "--no-input", "-q", "-r", str(lock)],
            check=True,
            timeout=3000,
        )

    def running(self, units) -> list:
        """The units to restart: all, or with `restart_running_only` the active ones, so a unit stopped by
        hand (an observer stopped for the real owner) stays stopped."""
        if not self.cfg.get("restart_running_only"):
            return list(units)
        sp = _sp()
        return [
            u
            for u in units
            if sp.run(["systemctl", "--user", "is-active", "--quiet", u], timeout=30).returncode == 0
        ]

    def restart(self, units) -> bool:
        """Restart the service units and report whether all are still active after `settle` seconds."""
        sp = _sp()
        complete = True
        try:
            if self.cfg.get("unit_files"):
                unit_dir = Path(self.cfg.get("unit_dir", "~/.config/systemd/user")).expanduser()
                for name in self.cfg["unit_files"]:
                    try:
                        shutil.copyfile(Path(self.cfg["root"]) / "current" / name, unit_dir / Path(name).name)
                    except OSError:
                        complete = False
                        log(step="unit_file_missing", file=name)
                try:
                    sp.run(["systemctl", "--user", "daemon-reload"], timeout=60)
                except subprocess.SubprocessError:
                    complete = False
            if not units:
                return complete
            if self.cfg.get("sequential"):
                for verb, ordered in (("stop", reversed(units)), ("start", units)):
                    for unit in ordered:
                        if sp.run(["systemctl", "--user", verb, unit], timeout=120).returncode != 0:
                            return False
            elif sp.run(["systemctl", "--user", "restart", *units], timeout=120).returncode != 0:
                return False
            _tm().sleep(self.cfg.get("settle", 10))
            active = all(
                sp.run(["systemctl", "--user", "is-active", "--quiet", unit], timeout=30).returncode == 0
                for unit in units
            )
            return complete and active
        except (OSError, subprocess.SubprocessError):
            return False

    def archive(self, sha: str, paths, target: Path) -> None:
        sp = _sp()
        mirror = Path(self.cfg["root"]) / "mirror.git"
        if not mirror.exists():
            sp.run(["git", "init", "--bare", "-q", str(mirror)], check=True)
        for stale in mirror.glob("*.lock"):
            stale.unlink()
        sp.run(
            ["git", "-C", str(mirror), "fetch", "-q", "--depth", "1", self.cfg["repo_url"], sha],
            check=True,
            timeout=600,
        )
        data = sp.run(
            ["git", "-C", str(mirror), "archive", "--format=tar", sha, *paths],
            capture_output=True,
            check=True,
            timeout=600,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(target, filter="data")

    def smoke(self, release: Path, python: Path) -> bool:
        done = _sp().run(
            [str(python), "-c", self.cfg.get("smoke", SMOKE)],
            cwd=release,
            capture_output=True,
            text=True,
            timeout=120,
        )
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
        shown = _sp().run(
            ["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "MainPID"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        props = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
        return props["MainPID"] if props.get("ActiveState") == "active" and props.get("MainPID", "0") != "0" else None

    def device_in_use(self) -> bool:
        sp = _sp()
        observed = {os.path.realpath(o["device"]): o["unit"] for o in self.cfg.get("observers", [])}
        for device in self.cfg["devices"]:
            resolved = os.path.realpath(device)
            found = sp.run(["fuser", resolved], capture_output=True, text=True)
            if found.returncode == 0:
                owners = found.stdout.split()
                if resolved not in observed or owners != [self._observer_pid(observed[resolved])]:
                    return True
        return False

    def follower_torque_off(self, release: Path, python: Path) -> bool:
        observers = self.cfg.get("observers")
        if observers:
            return all(self._observed_torque_off(o) for o in observers)
        code = (
            "import sys; sys.path.insert(0, 'deploy/robot/omx'); from joint_tune import SerialBus, FOLLOWER; "
            f"bus = SerialBus({self.cfg['follower_device']!r}, 0)\n"
            "try:\n    on = []\n    for m in FOLLOWER:\n        bus.motor = m\n        on.append(bus.read('torque'))\n"
            "finally:\n    bus.close()\nprint('torque', sum(on))"
        )
        done = _sp().run([str(python), "-c", code], cwd=release, capture_output=True, text=True, timeout=60)
        return done.returncode == 0 and done.stdout.strip() == "torque 0"

    def _observed_torque_off(self, observer: dict) -> bool:
        """The observer's own fresh motor-health snapshot: every expected motor reports torque OFF."""
        try:
            health = json.loads(Path(observer["health"]).read_text(encoding="utf-8"))
            motors = health["motors"]
            fresh = _tm().time() - float(health["observed_at"]) <= float(self.cfg.get("observer_max_age_s", 10))
            return (
                fresh
                and isinstance(motors, list)
                and len(motors) == health["expected_motor_count"] > 0
                and all(m.get("torque_enabled") is False for m in motors)
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def follower_missing(self) -> bool:
        return not self.cfg.get("observers") and not os.path.exists(self.cfg["follower_device"])
