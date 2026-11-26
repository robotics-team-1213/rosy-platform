"""2026-11-21: the cell task worker and the arm session wrappers it launches run one managed omx-devices release."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
WRAPPERS = OMX / "session-wrappers"
RELEASE = "%h/.local/share/rosy/omx-devices/current"
ARMS = {"arm_a": "with-session-arm-a-par.sh", "arm_b": "with-session-arm-b-par.sh", "arm_s": "with-session-arm-s-live.sh"}
for _p in (OMX, ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_task_exec as cte  # noqa: E402


def _unit() -> dict[str, str]:
    lines = (OMX / "rosy-omx-cell-task-worker.service").read_text(encoding="utf-8").splitlines()
    return {k: v for k, _, v in (ln.partition("=") for ln in lines if "=" in ln and not ln.startswith("Environment="))} | {
        f"env:{v.split('=', 1)[0]}": v.split("=", 1)[1] for ln in lines if ln.startswith("Environment=") for v in [ln[12:]]}


def test_worker_unit_runs_the_managed_release_and_the_r_site_name():
    unit = _unit()
    text = (OMX / "rosy-omx-cell-task-worker.service").read_text(encoding="utf-8")
    assert "omx-tools-current" not in text and "rosy-test" not in text
    assert unit["env:TOOLS_ROOT"] == RELEASE
    assert all(p.startswith(RELEASE) for p in unit["env:PYTHONPATH"].split(":"))
    argv = unit["ExecStart"].split()
    assert argv[1] == f"{RELEASE}/deploy/robot/omx/cell_task_worker.py"
    assert argv[argv.index("--fleet-r-url") + 1] == "https://rosy-fleet-r.local:8443"  # mDNS name, never an IP
    assert argv[argv.index("--ca-file") + 1] == "%h/.config/rosy/r-site-ca.pem"


def test_services_manifest_declares_the_worker_managed():
    entry = yaml.safe_load((ROOT / "deploy/hosts/services.yaml").read_text(encoding="utf-8"))["roles"]["omx"][
        "rosy-omx-cell-task-worker.service"]
    assert entry["channel"] == "autoupdate" and entry["source"] == ".local/share/rosy/omx-devices/current"
    assert entry["template"] == "deploy/robot/omx/rosy-omx-cell-task-worker.service" and entry["run"] == "active"


@pytest.mark.parametrize("arm,name", ARMS.items())
def test_wrappers_take_tools_from_the_release_and_keep_every_guard(arm, name):
    text = (WRAPPERS / name).read_text(encoding="utf-8")
    assert "\r" not in text and text.startswith("#!/bin/bash\n")
    for gone in ("omx-tools-current", "tools-env-current", "OMX_ENV", "ps -eo", "$ARM"):
        assert gone not in text, gone
    assert '. "$here/tools-env.sh"' in text
    for guard in (f"systemctl --user stop rosy-omx-observer@{arm}.service",
                  f"systemctl --user is-active --quiet rosy-omx-observer@{arm}.service",
                  f"flock -n ~/rosy-omx/session-{arm}.lock true",
                  "REFUSED: the arm session lock is held", "REFUSED: the arm session did not start", 'exec "$@"',
                  "omx-observation-bridge.env", f"--arm {arm}", "O_NONBLOCK",
                  'observer_handoff.py"', f"release {arm}", "kill -0 $bg_pid"):
        assert guard in text, guard


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
@pytest.mark.parametrize("arm,name", ARMS.items())
def test_wrappers_pass_bash_syntax_check(arm, name):
    res = subprocess.run([shutil.which("bash"), "-n", WRAPPERS.joinpath(name).as_posix()],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_tools_env_ignores_the_hand_switched_link():
    text = (WRAPPERS / "tools-env.sh").read_text(encoding="utf-8")
    assert "omx-tools-current" not in "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "/home/" not in text  # $HOME, no user baked in


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_tools_env_derives_omx_and_pythonpath_from_tools_root(tmp_path):
    script, bash = WRAPPERS.joinpath("tools-env.sh").as_posix(), shutil.which("bash")  # not Windows' System32 bash
    out = subprocess.run([bash, "-c", f'. "{script}"; printf "%s\\n%s\\n" "$OMX" "$PYTHONPATH"'], capture_output=True,
                         text=True, check=True, env={**os.environ, "TOOLS_ROOT": "/rel", "ROSY_OMX_EXTRA_SITE": "",
                                                     "PYTHONPATH": "/before"}).stdout.splitlines()
    assert out[0] == "/rel/deploy/robot/omx"
    assert out[1] == ("/rel/contracts/foundation:/rel/operations/overhead:/rel/middleware/devices/omx/adapter:"
                      "/rel/deploy/robot/omx:/before")
    env = {k: v for k, v in os.environ.items() if k != "TOOLS_ROOT"}  # unset: the release holding the file
    probe = subprocess.run([bash, "-c", f'. "{script}"; [ -f "$TOOLS_ROOT/deploy/robot/omx/session-wrappers/tools-env.sh" ] && echo ok'],
                           capture_output=True, text=True, env=env)
    assert probe.stdout.strip() == "ok", probe.stderr


def _run(tmp_path, monkeypatch, tools_root: Path | None):
    seen: dict = {}

    class P:
        returncode, stdout = 0, json.dumps({"result": "placed"})

    monkeypatch.setattr(cte.subprocess, "run", lambda cmd, **k: seen.update(cmd=cmd, env=k.get("env")) or P())
    monkeypatch.setattr(cte, "check_arm_hold", lambda a: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda a, p: {"folded": True, "state": None, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0})
    for n in ("with-session-arm-s-live.sh", "cell-auto-arm-s-live.json"):  # a stale prep-folder wrapper copy is ignored
        (tmp_path / n).write_text("{}")
    if tools_root is None:
        monkeypatch.delenv("TOOLS_ROOT", raising=False)
    else:
        (tools_root / "deploy/robot/omx/session-wrappers").mkdir(parents=True)
        (tools_root / "deploy/robot/omx/session-wrappers/with-session-arm-s-live.sh").write_text("#!/bin/bash\n")
        monkeypatch.setenv("TOOLS_ROOT", str(tools_root))
    cte.execute_guarded_cell_task({"arm_id": "arm_s", "task_id": "t", "handoff_lease_id": "l"}, prep_dir=tmp_path)
    return seen


def test_exec_launches_the_release_wrapper_and_passes_tools_root(tmp_path, monkeypatch):
    tools_root = tmp_path / "release"
    seen = _run(tmp_path, monkeypatch, tools_root)
    assert Path(seen["cmd"][0]) == tools_root / "deploy/robot/omx/session-wrappers/with-session-arm-s-live.sh"
    assert seen["env"]["TOOLS_ROOT"] == str(tools_root)


def test_exec_without_tools_root_uses_its_own_release(tmp_path, monkeypatch):
    seen = _run(tmp_path, monkeypatch, None)
    assert Path(seen["cmd"][0]) == WRAPPERS / "with-session-arm-s-live.sh"
    assert Path(seen["env"]["TOOLS_ROOT"]) == ROOT
