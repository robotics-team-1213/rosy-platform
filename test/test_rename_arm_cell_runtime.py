"""D-1011 maintenance regression with fake Compose and a real session flock."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest


RUNBOOK = Path(__file__).resolve().parents[1] / "tools/ops/rename_arm_cell_runtime.sh"

DOCKER = """#!/usr/bin/env bash
set -eu
case "$1" in
  ps)
    if [ "$2" = -aq ]; then printf '%s\\n' cell-a-fleet cell-a-vision cell-a-peer-cell-a; fi
    ;;
  volume)
    [ "$2" = inspect ] || exit 15
    [ "$3" = cell-a_cell_a_data ]
    ;;
  inspect)
    case "$3" in
      *config_files*)
        directory="$FIXTURE_DIR/cell-a"
        files="$directory/compose.yaml"
        env=""
        case "$SCENARIO" in
          overlay_dry|overlay_apply)
            files="$files,$directory/compose.d1039.yaml"
            env="$directory/cell-a.env"
            ;;
          overlay) files="$files,$directory/compose.different.yaml" ;;
        esac
        printf '%s|%s|%s\\n' "$files" "$directory" "$env"
        ;;
      *.Mounts*)
        if [[ "$4" = cell-a-* ]]; then echo cell-a_cell_a_data; else echo arm-cell_arm_cell_data; fi
        ;;
      *.State.Health*)
        if [ "$SCENARIO" = peer ] && [ "$4" = cell-a-peer-cell-a ]; then
          echo no-healthcheck
        else
          echo healthy
        fi
        ;;
    esac
    ;;
  compose)
    project="$3"; directory="$5"; shift 5
    case "$SCENARIO" in
      overlay_dry|overlay_apply)
        [ "$1" = --env-file ] && [ "$2" = "$directory/cell-a.env" ]
        shift 2
        [ "$1" = -f ] && [ "$2" = "$directory/compose.yaml" ]
        [ "$3" = -f ] && [ "$4" = "$directory/compose.d1039.yaml" ]
        file="$2"; shift 4
        echo "verified overlay and env" >> "$FIXTURE_DIR/actions"
        ;;
      *) file="$2"; shift 2 ;;
    esac
    [ "$file" = "$directory/compose.yaml" ] && [ -f "$file" ]
    case "$1" in
      ps) printf '%s-%s\\n' "$project" "$3" ;;
      config) ;;
      *) exit 15 ;;
    esac
    ;;
  *) exit 15 ;;
esac
"""

SYSTEMCTL = """#!/usr/bin/env bash
active=inactive; installed=disabled
if [ "$SCENARIO" = updater_active ] && [ "$3" = rosy-cell-autoupdate.service ]; then active=activating; fi
if [ "$SCENARIO" = updater_enabled ] && [ "$3" = rosy-cell-autoupdate.timer ]; then installed=enabled; fi
printf 'LoadState=loaded\\nActiveState=%s\\nUnitFileState=%s\\n' "$active" "$installed"
"""


@pytest.mark.parametrize(
    ("scenario", "expected_message"),
    [
        ("overlay", "live Compose provenance differs"),
        ("overlay_dry", "preflight passed"),
        ("overlay_apply", "preflight only; live switch requires"),
        ("single_apply", "preflight only; live switch requires"),
        ("peer", "peer-cell-a=no-healthcheck"),
        ("updater_active", "legacy updater rosy-cell-autoupdate.service is active"),
        ("updater_enabled", "legacy updater rosy-cell-autoupdate.timer is enabled"),
        ("stale_s", "arm_s lacks fresh complete passive torque-OFF evidence"),
        ("stale_motor", "arm_s lacks fresh complete passive torque-OFF evidence"),
        ("job_lock", "active job locks"),
        ("success", "preflight passed"),
    ],
)
def test_arm_cell_runtime_rename(tmp_path, scenario, expected_message):
    if os.name != "posix" or not shutil.which("bash") or not shutil.which("flock"):
        pytest.skip("requires Linux shell and flock")
    old_dir = tmp_path / "cell-a"
    old_dir.mkdir()
    old_yaml = "volumes:\n  cell_a_data: {}\nnetworks:\n  cell_a_backend: {}\n"
    (old_dir / "compose.yaml").write_text(old_yaml)
    if scenario in {"overlay_dry", "overlay_apply"}:
        (old_dir / "compose.d1039.yaml").write_text("services: {}\n")
        (old_dir / "cell-a.env").write_text("ROSY_SITE_FLEET_TAG=fixture\n")
    operator = tmp_path / "operator"
    sessions = operator / "rosy-omx"
    sessions.mkdir(parents=True)
    (sessions / "session.lock").touch()
    jobs = operator / "rosy-jobs"
    jobs.mkdir()
    if scenario == "job_lock":
        (jobs / "active.lock").touch()
    health_dir = operator / ".local/state/rosy/motor-health"
    health_dir.mkdir(parents=True)
    for arm in ("arm_a", "arm_b", "arm_s"):
        observed = time.time() - (30 if arm == "arm_s" and scenario == "stale_s" else 0)
        (health_dir / f"{arm}.json").write_text(json.dumps({
            "schema_version": "rosy.motor-health.v1",
            "owner_id": arm,
            "status": "active",
            "observed_at": observed,
            "expected_motor_count": 6,
            "motors": [
                {"id": number, "group": arm, "torque_enabled": False, "fault": False,
                 "observed_at": observed - (30 if arm == "arm_s" and number == 11 and scenario == "stale_motor" else 0)}
                for number in range(11, 17)
            ],
        }))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in (("docker", DOCKER), ("systemctl", SYSTEMCTL),
                          ("id", "#!/usr/bin/env bash\necho 0\n")):
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    runbook = RUNBOOK.read_text().replace("/etc/rosy/", f"{tmp_path}/")
    result = subprocess.run(
        ["bash", "-s", "--"] + (["--apply"] if scenario.endswith("_apply") else []),
        input=runbook,
        env=dict(os.environ, FIXTURE_DIR=str(tmp_path), OPERATOR_HOME=str(operator),
                 SCENARIO=scenario, PATH=f"{bin_dir}:{os.environ['PATH']}"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert expected_message in result.stdout + result.stderr
    assert (result.returncode == 0) == (scenario in {"success", "overlay_dry"})
    actions = tmp_path / "actions"
    if scenario == "overlay_dry":
        assert "verified overlay and env" in actions.read_text()
    if scenario.endswith("_apply"):
        assert not actions.exists()
    assert not (tmp_path / "arm-cell").exists()
    assert not old_dir.is_symlink()
    assert (old_dir / "compose.yaml").read_text() == old_yaml
