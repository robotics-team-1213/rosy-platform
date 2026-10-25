#!/usr/bin/env python3
"""Move a running Learning center to the newest green main while no center job runs (D-871).

The installer (`install_learning_center.py`) pins the unit to one clean checkout `source/<full sha>` and
keeps the existing review state only when the installed unit is exactly the text the new commit writes.
One run automates the 2026-10-23 procedure
(docs/solutions/deployment/learning-center-upgrade-needs-the-identical-unit-first-2026-10-23.md):

1. the center must be enabled and active; a center stopped by hand is left alone (`idle`);
2. trust gate as `omx_autoupdate.py`: every required check green from GitHub Actions and the commit
   descends from the installed one; a commit that failed before is not retried until main moves;
3. idle: no `experiment_train`/`experiment_online`/`experiment_export` process on the host and nothing
   but the review app in the unit's cgroup, otherwise `held`;
4. fetch the commit into `source/<full sha>` (detached, clean) and render its unit with the new
   installer's own `prepare()`, reusing the running unit's --state, --center-config, --python, --port,
   and --collaboration;
5. back up the unit, stop the center, write the new unit and run the new installer with `--apply`;
6. healthy = active, ExecStart names the new source and `http://127.0.0.1:<port>/` answers 200 within
   `settle` seconds; otherwise the backup unit is restored, reloaded and started again.

  learning_center_update.py --config ~/.config/rosy/learning-center-update.json run [--dry-run]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

SERVICE = "rosy-learning-center.service"
INSTALLER = Path("deploy/model_pc/install_learning_center.py")
UPDATER = Path("deploy/model_pc/learning_center_update.py")
JOBS = ("experiment_train", "experiment_online", "experiment_export")
KEEP_FLAGS = ("--state", "--center-config", "--python", "--port", "--collaboration")


def log(**row):
    row["t"] = round(time.time(), 3)
    print(json.dumps(row, default=str), flush=True)


def load_omx_autoupdate():
    """The cell updater's GitHub trust checks, from the same checkout as this file."""
    path = Path(__file__).resolve().parents[1] / "robot/omx/omx_autoupdate.py"
    spec = importlib.util.spec_from_file_location("omx_autoupdate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installer_args(unit_text: str) -> dict:
    """The installer's own arguments from the unit's ExecStartPre check line."""
    for line in unit_text.splitlines():
        if line.startswith("ExecStartPre=") and INSTALLER.as_posix() in line:
            words = shlex.split(line[len("ExecStartPre="):])
            args, i = {"python": words[0]}, 2
            while i < len(words):
                if words[i].startswith("--") and i + 1 < len(words) and not words[i + 1].startswith("--"):
                    args[words[i]] = words[i + 1]
                    i += 2
                else:
                    i += 1
            if "--commit" in args and "--source-root" in args:
                return args
    raise ValueError("the unit has no installer check line")


class Host:
    """Everything that touches GitHub, git, systemd, processes and HTTP; replaced by fakes in tests."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.github = load_omx_autoupdate().Host(cfg)
        self.unit_path = Path(cfg.get("unit_dir", "~/.config/systemd/user")).expanduser() / SERVICE

    def remote_head(self) -> str:
        return self.github.remote_head()

    def checks(self, sha: str) -> dict:
        return self.github.checks(sha)

    def descends(self, base: str, head: str) -> bool:
        return self.github.descends(base, head)

    def unit_text(self) -> str | None:
        return self.unit_path.read_text(encoding="utf-8") if self.unit_path.is_file() else None

    def write_unit(self, text: str) -> None:
        self.unit_path.write_text(text, encoding="utf-8")

    def systemctl(self, *args: str) -> int:
        return subprocess.run(["systemctl", "--user", *args], timeout=120).returncode

    def running_center(self) -> bool:
        return self.systemctl("is-enabled", "--quiet", SERVICE) == 0 and \
            self.systemctl("is-active", "--quiet", SERVICE) == 0

    def busy(self) -> str | None:
        found = subprocess.run(["pgrep", "-af", "|".join(JOBS)], capture_output=True, text=True, timeout=30)
        if any(job in found.stdout for job in JOBS):
            return "center_job_running"
        group = subprocess.run(["systemctl", "--user", "show", SERVICE, "-p", "ControlGroup", "--value"],
                               capture_output=True, text=True, timeout=30).stdout.strip()
        procs = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
        try:
            pids = procs.read_text().split()
        except OSError:
            return "center_cgroup_unreadable"
        for pid in pids:
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "review_app.py" not in cmd:
                return "center_child_process"
        return None

    def fetch(self, sha: str, target: Path) -> None:
        staging = target.with_name(target.name + ".tmp")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for args in (["init", "-q"], ["fetch", "-q", "--depth", "1", self.cfg["repo_url"], sha],
                     ["checkout", "-q", "--detach", sha]):
            subprocess.run(["git", "-C", str(staging), *args], check=True, timeout=900)
        os.replace(staging, target)

    def render(self, source: Path, args: dict, sha: str) -> str:
        """The unit text the new commit's installer writes for the same state and center."""
        spec = importlib.util.spec_from_file_location("install_learning_center", source / INSTALLER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.prepare(self.namespace(source, args, sha))[0]

    def namespace(self, source: Path, args: dict, sha: str) -> argparse.Namespace:
        get = lambda flag: Path(args[flag]) if args.get(flag) else None  # noqa: E731
        return argparse.Namespace(source_root=source, commit=sha, state=get("--state"),
                                  center_config=get("--center-config"), python=Path(args["python"]),
                                  port=int(args.get("--port", 8769)), collaboration=get("--collaboration"),
                                  apply=True)

    def apply(self, source: Path, args: dict, sha: str) -> bool:
        command = [args["python"], str(source / INSTALLER), "--source-root", str(source), "--commit", sha]
        for flag in KEEP_FLAGS:
            if args.get(flag) and flag != "--python":
                command += [flag, args[flag]]
        command += ["--python", args["python"], "--apply"]
        return subprocess.run(command, timeout=600).returncode == 0  # the installer's own exit, never a pipe's

    def healthy(self, sha: str, port: int) -> bool:
        deadline = time.time() + self.cfg.get("settle", 60)
        while time.time() < deadline:
            shown = subprocess.run(["systemctl", "--user", "show", SERVICE, "-p", "ExecStart", "--value"],
                                   capture_output=True, text=True, timeout=30).stdout
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as answer:
                    ok = answer.status == 200
            except OSError:
                ok = False
            if ok and f"source/{sha}/" in shown and self.systemctl("is-active", "--quiet", SERVICE) == 0:
                return True
            time.sleep(3)
        return False


class Updater:
    def __init__(self, cfg: dict, host) -> None:
        self.cfg, self.host = cfg, host
        self.sources = Path(cfg["source_root"]).expanduser()
        self.state_path = Path(cfg.get("state_file", "~/.local/state/rosy/learning-center-update.json")).expanduser()

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {"history": []}

    def save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)

    def restore(self, unit: str) -> None:
        """The backed-up unit, byte for byte, and a restart: the new code may already be running under it."""
        self.host.write_unit(unit)
        self.host.systemctl("daemon-reload")
        self.host.systemctl("restart", SERVICE)

    def point_current(self, sha: str) -> None:
        """`current` names the installed checkout, so the timer runs this updater from the live commit."""
        link, target = self.sources.parent / "current", f"{self.sources.name}/{sha}"
        # an older checkout without this updater would leave the timer with nothing to run
        if (self.sources / sha / UPDATER).is_file() and (not link.is_symlink() or os.readlink(link) != target):
            tmp = link.with_name("current.tmp")
            if tmp.is_symlink():
                tmp.unlink()
            tmp.symlink_to(target)
            os.replace(tmp, link)

    def finish(self, state: dict, step: str, **row) -> str:
        state["last"] = {"step": step, "at": time.time(), **row}
        self.save(state)
        log(step=step, **row)
        return step

    def run(self, *, dry_run: bool = False) -> str:
        state = self.state()
        unit = self.host.unit_text()
        if unit is None:
            return self.finish(state, "not_installed")
        args = installer_args(unit)
        installed = args["--commit"]
        if not dry_run:
            self.point_current(installed)
        if not self.host.running_center():  # stopped or disabled by hand: never start it from here
            # "idle", not "held": nothing to move, so update_status does not report it STUCK
            return self.finish(state, "idle", reason="center_not_running", release=installed[:12])
        sha = self.host.remote_head()
        if sha == installed:
            return self.finish(state, "up_to_date", release=sha[:12])
        if sha == state.get("failed"):
            return self.finish(state, "known_bad", release=sha[:12])
        for required in self.cfg["required_checks"]:
            status = self.host.checks(sha).get(required)
            if status is None or status[0] != "completed":
                return self.finish(state, "waiting_ci", release=sha[:12])
            if status[1] != "success" or status[2] != "github-actions":
                return self.finish(state, "ci_failed", release=sha[:12])
        if not self.host.descends(installed, sha):
            return self.finish(state, "not_descendant", release=sha[:12])
        busy = self.host.busy()
        if busy:
            return self.finish(state, "held", reason=busy, release=sha[:12])
        if dry_run:
            return self.finish(state, "would_switch", release=sha[:12])
        source = self.sources / sha
        if not source.exists():
            try:
                self.host.fetch(sha, source)
            except (OSError, subprocess.SubprocessError) as error:  # network or git: retried next run
                return self.finish(state, "fetch_failed", release=sha[:12], error=str(error))
        try:
            new_unit = self.host.render(source, args, sha)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:  # the new installer refuses
            state["failed"] = sha
            return self.finish(state, "render_failed", release=sha[:12], error=str(error))
        backup = self.host.unit_path.with_name(f"{SERVICE}.bak-{installed[:10]}-{time.strftime('%Y%m%d%H%M%S')}")
        backup.write_text(unit, encoding="utf-8")
        if self.host.systemctl("stop", SERVICE) != 0:  # the old process would answer the health check
            # A timed-out stop is still killed: start the unchanged unit, a no-op if the old process lives on.
            self.host.systemctl("start", SERVICE)
            return self.finish(state, "held", reason="stop_failed", release=sha[:12])
        try:
            switched = (self.host.write_unit(new_unit) is None and self.host.apply(source, args, sha)
                        and self.host.healthy(sha, int(args.get("--port", 8769))))
        except BaseException:
            self.restore(unit)
            raise
        if switched:
            state["history"] = (state["history"] + [{"release": sha[:12], "result": "active", "at": time.time()}])[-50:]
            state.update(current=sha, previous=installed)
            self.point_current(sha)
            return self.finish(state, "switched", release=sha[:12], previous=installed[:12])
        self.restore(unit)
        state["failed"] = sha
        state["history"] = (state["history"] + [{"release": sha[:12], "result": "rolled_back", "at": time.time()}])[-50:]
        return self.finish(state, "rolled_back", release=sha[:12], to=installed[:12])


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("branch", "main")
    cfg.setdefault("required_checks", ["ci-result"])
    cfg.setdefault("source_root", "~/.local/share/rosy-learning-center/source")
    missing = [k for k in ("repo_url", "github_repo") if not cfg.get(k)]
    if missing or not cfg["required_checks"]:
        raise SystemExit(f"config needs {missing or 'required_checks'}")
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path,
                        default=Path("~/.config/rosy/learning-center-update.json").expanduser())
    parser.add_argument("command", choices=("run",))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    result = Updater(cfg, Host(cfg)).run(dry_run=args.dry_run)
    sys.exit(1 if result in {"ci_failed", "render_failed", "rolled_back"} else 0)


if __name__ == "__main__":
    main()
