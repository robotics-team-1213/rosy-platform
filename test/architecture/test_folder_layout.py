"""D-186: scripts and module markdown do not grow a second owner."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _modules() -> set[str]:
    registry = yaml.safe_load((ROOT / "tools" / "harness" / "harness.yaml").read_text(encoding="utf-8"))
    return {item["path"].replace("\\", "/") for item in registry["modules"]}


def test_root_shell_is_only_the_dev_environment():
    shells = sorted(path.name for path in ROOT.glob("*.sh"))
    assert shells == ["env.sh"]


def test_package_trees_do_not_carry_a_second_installer():
    assert list(ROOT.glob("src/**/deploy/*.sh")) == []
    assert (ROOT / "middleware" / "devices" / "pinky" / "bringup" / "scripts" / "rosy_env.sh").is_file()
    assert (ROOT / 'tools' / 'sim' / 'gazebo' / "run_track260905.sh").is_file()


def test_umbrella_scripts_live_in_the_repo():
    sim = ROOT / "tools" / "sim" / "sim_verify.sh"
    text = sim.read_text(encoding="utf-8")
    assert "/mnt/f/" not in text
    assert "tools/run_fleet_sim.sh" in text
    assert (ROOT / "docs" / "assessments" / "communication-protocol-report.md").is_file()
    assert (ROOT / "docs" / "assessments" / "module-coupling-scorecard.md").is_file()


def test_developer_scripts_live_under_tools():
    assert (ROOT / "tools" / "fix_ament_resource.sh").is_file()
    assert (ROOT / "tools" / "run_fleet_sim.sh").is_file()
    assert "/mnt/f/" not in (ROOT / "tools" / "fix_ament_resource.sh").read_text(encoding="utf-8")


def test_deployment_sources_group_by_robot_product():
    pinky = ROOT / "deploy" / "robot" / "pinky_pro"
    omx = ROOT / "deploy" / "robot" / "omx"
    assert (pinky / "image" / "build-image.sh").is_file()
    assert (pinky / "release" / "build_payload_release.py").is_file()
    assert (pinky / "sd" / "write-card.ps1").is_file()
    assert (pinky / "native" / "rosy-runtime.target").is_file()
    assert (omx / "README.md").is_file()
    assert (ROOT / "deploy" / "site" / "compose.yaml").is_file()
    def contains_source(path: Path) -> bool:
        if not path.exists():
            return False
        return any(
            item.is_file()
            and item.suffix != ".pyc"
            and "__pycache__" not in item.parts
            and ".pytest_cache" not in item.parts
            for item in path.rglob("*")
        )

    assert not contains_source(ROOT / "deploy" / "image")
    assert not contains_source(ROOT / "deploy" / "release")
    assert not contains_source(ROOT / "deploy" / "sd")
    assert not contains_source(ROOT / "deploy" / "omx")


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                    reason="ament marker repair requires a Linux bash workspace")
def test_ament_marker_repair_reaches_nested_product_packages(tmp_path):
    workspace = tmp_path / "rosy"
    tools = workspace / "tools"
    tools.mkdir(parents=True)
    script = tools / "fix_ament_resource.sh"
    shutil.copy2(ROOT / "tools" / "fix_ament_resource.sh", script)

    packages = {
        "middleware/devices/pinky/profile": "pinky_pro",
        "middleware/devices/omx/adapter": "omx_adapter",
        "middleware/drivers/imu_bno055": "imu_bno055",
    }
    for relative in ("contracts", "middleware", "operations", "integrations", "learning"):
        (workspace / relative).mkdir()
    for relative, name in packages.items():
        package = workspace / relative
        package.mkdir(parents=True)
        (package / "setup.py").write_text("# ament_python package\n", encoding="utf-8")
        (package / "package.xml").write_text(
            f"<package><name>{name}</name></package>\n", encoding="utf-8"
        )

    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for relative, name in packages.items():
        assert (workspace / relative / "resource" / name).is_file(), relative


_FROZEN_VALIDATION_PYTHON = {
    'ai-pc-lane-ring-replay-2026-10-09/replay.py',
    'lane-goal-sim-2026-10-08/analyze_bend_memory.py',
    'lane-goal-sim-2026-10-08/analyze_edge.py',
    'lane-goal-sim-2026-10-08/analyze_map_bend.py',
    'lane-ground-debug-ros-smoke-2026-10-08/probe.py',
    'map-v2-fleet-keep-2026-09-30/keep_run.py',
    'map-v2-fleet-keep-2026-09-30/make_video.py',
    'map-v2-fleet-real-profile-2026-09-30/capture_frames.py',
    'map-v2-fleet-real-profile-2026-09-30/sheet.py',
}


def _validation_scripts_outside_evidence(root):
    return sorted(path.relative_to(root).as_posix()
                  for pattern in ('*.sh', '*.py') for path in root.rglob(pattern)
                  if 'evidence' not in path.relative_to(root).parts
                  and path.relative_to(root).as_posix() not in _FROZEN_VALIDATION_PYTHON)


def test_validation_scripts_stay_inside_evidence():
    assert _validation_scripts_outside_evidence(ROOT / 'docs/validation') == []


def test_validation_guard_rejects_new_python_outside_evidence(tmp_path):
    (tmp_path / 'new.py').write_text('print(1)\n', encoding='utf-8')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'allowed.py').write_text('print(1)\n', encoding='utf-8')
    assert _validation_scripts_outside_evidence(tmp_path) == ['new.py']


def test_module_gate_markdown_stays_on_the_module():
    modules = _modules()
    # Linked checkouts (.worktrees, .claude/worktrees) are other trees, not this one.
    skip = {".git", ".worktrees", "worktrees", "build", "install", "log", "__pycache__"}
    stray = []
    for name in ("progress.md", "logs.md", "index.md"):
        for path in ROOT.rglob(name):
            if any(part in skip for part in path.parts):
                continue
            parent = path.parent.relative_to(ROOT).as_posix()
            if parent not in modules:
                stray.append(path.relative_to(ROOT).as_posix())
    assert stray == []


def test_current_docs_do_not_point_at_retired_paths():
    # Build/sim commands moved from README to the developer guide on 2026-10-05.
    readme = (ROOT / "docs" / "reference" / "developer-guide.md").read_text(encoding="utf-8")
    assert "tools/run_fleet_sim.sh" in readme
    assert "tools/fix_ament_resource.sh" in readme
    assert "data/teleop" in readme


def test_capture_markdown_is_only_the_data_readme():
    data = ROOT / "data"
    markdown = sorted(path.relative_to(data).as_posix() for path in data.rglob("*.md"))
    assert markdown == ["README.md"]
    assert (data / "teleop").is_dir()
    assert (data / "drive").is_dir()
    learning = data / "teleop" / "learning"
    # New sessions land here too (gitignored, D-379); the seven tracked clips must stay.
    clips = sorted(path.name for path in learning.glob("*.mp4"))
    assert set(clips) >= {
        "teleop_20260919_151213_part01.mp4",
        "teleop_20260919_151213_part02.mp4",
        "teleop_20260919_151213_part03.mp4",
        "teleop_20260919_151213_part04.mp4",
        "teleop_20260919_151213_part05.mp4",
        "teleop_20260919_151213_part06.mp4",
        "teleop_20260919_151213_part07.mp4",
    }
    assert not (ROOT / "video").exists()
