"""Contracts for the native ARM64 unsigned-payload workflow."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-arm64-payload.yml"
RUNBOOK = ROOT / "docs" / "deployment" / "pinky-pro-first-device-runbook.md"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_payload_workflow_is_manual_native_and_unsigned():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    job = workflow["jobs"]["build-unsigned-payload"]

    assert set(triggers) == {"workflow_dispatch"}
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert job.get("continue-on-error") is not True
    assert "contents: read" in WORKFLOW.read_text(encoding="utf-8")
    assert "private" not in " ".join(job.get("env", {})).lower()


def test_payload_workflow_runs_guarded_builder_and_uploads_checksums():
    workflow = _workflow()
    job = workflow["jobs"]["build-unsigned-payload"]
    rendered = WORKFLOW.read_text(encoding="utf-8")
    steps = job["steps"]

    assert "deploy/robot/pinky_pro/release/arm64_release_builder.py" in rendered
    assert "--ros-image \"$ROS_IMAGE\"" in rendered
    assert "docker system prune --all --force" in rendered
    assert "sha256sum" in rendered
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["compression-level"] == 0
    assert "unsigned" in upload["with"]["name"]


def test_payload_workflow_pins_the_documented_ros_base_digest():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    default = triggers["workflow_dispatch"]["inputs"]["ros_image"]["default"]
    digest = "".join((
        "c3706ef0", "a0aa4541", "3c07803c", "f433602f",
        "543b22e4", "5b4855f6", "fca955c2", "d8ecc4e8",
    ))

    assert default == "ros:jazzy-ros-base@sha256:" + digest


def test_first_device_runbook_keeps_unsigned_artifact_out_of_g0():
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "gh workflow run build-arm64-payload.yml" in text
    assert "It still does not sign" in text
    assert "offline signing environment" in text
