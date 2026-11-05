"""Fail-closed Pinky artifact selection contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from artifact_impact import classify_paths, select_impact

ROOT = Path(__file__).resolve().parents[1]


def test_docs_tests_and_external_robot_products_need_no_pinky_artifact():
    report = classify_paths(
        [
            "docs/deployment/example.md",
            "test/test_example.py",
            ".github/workflows/ci.yml",
            "deploy/robot/omx/compose.yaml",
            "deploy/site/compose.yaml",
        ]
    )

    assert report.impact == "none"
    assert all(item.impact == "none" for item in report.paths)


def test_ros_workspace_changes_choose_native_payload():
    report = classify_paths(
        ["middleware/core/gateway/core/api.py", "learning/envs/isaac/bridge.py"]
    )

    assert report.impact == "native-payload"
    assert report.paths[0].impact == "native-payload"


def test_every_manifest_colcon_root_chooses_native_payload():
    # D-427 wave 0 item 5: the payload builds every colcon root, so each one is native-payload.
    import yaml

    manifest = ROOT / "tools" / "harness" / "platform_parts.yaml"
    roots = yaml.safe_load(manifest.read_text(encoding="utf-8"))["colcon_roots"]
    report = classify_paths([f"{root}/some_package/module.py" for root in roots])

    assert roots and [item.impact for item in report.paths] == ["native-payload"] * len(roots)
    assert classify_paths([f"{roots[0]}x/module.py"]).impact == "review"


def test_image_or_host_foundation_changes_choose_flashable_image():
    report = classify_paths(
        [
            "middleware/devices/pinky/bringup/launch/robot.launch.py",
            "deploy/robot/pinky_pro/image/inputs.lock.yaml",
        ]
    )

    assert report.impact == "flashable-image"


def test_unclassified_pinky_paths_force_review_even_with_payload_changes():
    report = classify_paths(
        [
            "middleware/core/gateway/core/api.py",
            "deploy/robot/pinky_pro/release/updater.py",
        ]
    )

    assert report.impact == "review"
    by_path = {item.path: item for item in report.paths}
    assert by_path["deploy/robot/pinky_pro/release/updater.py"].impact == "review"


def test_empty_diff_needs_no_robot_artifact():
    assert classify_paths([]).impact == "none"


def test_signed_boot_support_and_native_runtime_choose_payload_but_os_inputs_require_image():
    for path in ('deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.py',
                 'deploy/robot/pinky_pro/image/first-boot/rosy-first-boot.sh',
                 'deploy/robot/pinky_pro/native/network_agent.py',
                 'deploy/robot/pinky_pro/native/rosy-network-agent.service'):
        assert classify_paths([path]).impact == 'native-payload'
    assert classify_paths(['deploy/robot/pinky_pro/image/inputs.lock.yaml']).impact == 'flashable-image'
    assert classify_paths(['deploy/robot/pinky_pro/native/unlisted.service']).impact == 'review'


def test_selector_reads_changed_paths_from_the_git_merge_base(tmp_path: Path):
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("before\n", encoding="utf-8")
    git("add", "docs/guide.md")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")

    runtime_path = "middleware/perception/control/node.py"
    runtime_file = tmp_path / runtime_path
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("def run(): pass\n", encoding="utf-8")
    git("add", runtime_path)
    git("commit", "-qm", "runtime change")
    head = git("rev-parse", "HEAD")

    report = select_impact(base, head, repository=tmp_path)

    assert report.base == base
    assert report.head == head
    assert report.impact == "native-payload"
    assert [item.path for item in report.paths] == [runtime_path]

    release_tool = tmp_path / "deploy" / "robot" / "pinky_pro" / "release" / "updater.py"
    release_tool.parent.mkdir(parents=True)
    release_tool.write_text("# requires review\n", encoding="utf-8")
    git("add", "deploy/robot/pinky_pro/release/updater.py")
    git("commit", "-qm", "unclassified Pinky tooling change")
    review_head = git("rev-parse", "HEAD")
    command = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy" / "robot" / "pinky_pro" / "release" / "artifact_impact.py"),
            "--base",
            head,
            "--head",
            review_head,
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert command.returncode == 3
    assert command.stdout.startswith("PINKY_ARTIFACT=review")


def test_retired_source_root_requires_review_instead_of_implicit_payload():
    report = classify_paths(["src/node.py", "middleware/perception/control/node.py"])
    assert report.impact == "review"
    assert {item.path: item.impact for item in report.paths} == {
        "src/node.py": "review",
        "middleware/perception/control/node.py": "native-payload",
    }


def test_shipped_support_is_not_hidden_by_host_tool_rules():
    for path in ("tools/packaging/fleet_sources.py",
                 "deploy/robot/pinky_pro/release/host_lane_perception.py"):
        assert classify_paths([path]).impact == "native-payload", path
    # This implementation is also copied by the Pinky installer. A host folder
    # name must never become permission to discard an unreviewed dependency.
    assert classify_paths(["deploy/hosts/common/release/signing.py"]).impact != "none"


def test_checkout_and_sd_closure_require_os_delivery():
    for path in (".gitattributes", "deploy/robot/pinky_pro/sd/media-layout.ps1",
                 "deploy/robot/pinky_pro/sd/test/Setup-MovedDevice.Tests.ps1",
                 "deploy/robot/pinky_pro/sd/new-install-helper.py"):
        assert classify_paths([path]).impact == "flashable-image", path


def test_host_role_prefixes_and_reviewed_exact_tools_need_no_device_artifact():
    for path in ("deploy/ai_pc/host-state/manifest", "deploy/model_pc/install_review_release.py",
                 "deploy/hosts/common/host-state/manifest", "deploy/hosts/gpu_tenants.py",
                 "deploy/hosts/common/release/native_profiles.py",
                 "tools/calibration/analyze_session.py", "tools/capture/drivable_steer.py",
                 "tools/perception_prototype/realrun/replay.py", "tools/remote/robot_status.py",
                 "tools/sim/transfer_observer.py", "tools/release/robot_cd.py",
                 "tools/land_selection.py", "tools/graphify_pipeline.py",
                 "tools/hooks/land_record.py", "tools/publish_main.py", "tools/worktrees.py"):
        assert classify_paths([path]).impact == "none", path


def test_exact_development_and_policy_files_do_not_change_native_artifacts():
    for path in (".dockerignore", "CONCEPTS.md", "DESIGN.md",
                 "deploy/robot/pinky_pro/Dockerfile", "deploy/robot/pinky_pro/compose.yaml",
                 "deploy/robot/pinky_pro/release/artifact_impact.py",
                 "deploy/robot/pinky_pro/release/public_provenance.json",
                 "deploy/robot/pinky_pro/release/publish_secret_baseline.json"):
        assert classify_paths([path]).impact == "none", path


def test_new_tool_and_host_paths_remain_review_even_beside_known_scopes():
    for path in ("tools/new_device_writer.py", "tools/packaging/unreviewed.py",
                 "tools/land_future.py", "deploy/hosts/new-service.py",
                 "deploy/hosts/common/release/unreviewed.py",
                 "deploy/robot/pinky_pro/Dockerfile.future", ".gitattributes.future"):
        assert classify_paths([path]).impact == "review", path
        assert classify_paths([path, ".gitattributes",
                               "middleware/core/gateway/core/api.py"]).impact == "review", path


def test_operator_calibration_probe_is_exact_host_scope_not_a_pinky_prefix():
    # Push/ship execute the guard on the PC; its helper is a read-only SSH stdin
    # probe, not a persistent image/payload install destination.
    for name in ("calibration_tls_read.py", "rosy-calibration-guard.ps1"):
        assert classify_paths([f"deploy/robot/pinky_pro/{name}"]).impact == "none", name
    assert classify_paths(["deploy/robot/pinky_pro/unreviewed-guard.ps1"]).impact == "review"
