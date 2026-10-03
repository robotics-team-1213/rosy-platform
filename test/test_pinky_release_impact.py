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
        ["src/runtime/gateway/core/api.py", "src/sim/isaac_sim/bridge.py"]
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
            "src/products/pinky_pro/bringup/launch/robot.launch.py",
            "deploy/robot/pinky_pro/image/inputs.lock.yaml",
        ]
    )

    assert report.impact == "flashable-image"


def test_unclassified_pinky_paths_force_review_even_with_payload_changes():
    report = classify_paths(
        [
            "src/runtime/gateway/core/api.py",
            "deploy/robot/pinky_pro/release/updater.py",
        ]
    )

    assert report.impact == "review"
    by_path = {item.path: item for item in report.paths}
    assert by_path["deploy/robot/pinky_pro/release/updater.py"].impact == "review"


def test_empty_diff_needs_no_robot_artifact():
    assert classify_paths([]).impact == "none"


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

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "node.py").write_text("def run(): pass\n", encoding="utf-8")
    git("add", "src/node.py")
    git("commit", "-qm", "runtime change")
    head = git("rev-parse", "HEAD")

    report = select_impact(base, head, repository=tmp_path)

    assert report.base == base
    assert report.head == head
    assert report.impact == "native-payload"
    assert [item.path for item in report.paths] == ["src/node.py"]

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
