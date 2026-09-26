"""Contracts for the D-225 2.1 native payload-only workflow."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-native-payload.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job():
    return _workflow()["jobs"]["build-unsigned-payload"]


def _run_text() -> str:
    return "\n".join(step.get("run", "") for step in _job()["steps"])


def test_manual_native_arm64_and_read_only():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    job = _job()

    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["release_id"]["required"] is True
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert job.get("continue-on-error") is not True
    assert workflow["permissions"] == {"contents": "read"}


def test_no_secrets_and_no_signing_in_ci():
    rendered = WORKFLOW.read_text(encoding="utf-8")

    assert "secrets." not in rendered
    assert "sign_image_release" not in _run_text()
    assert "private" not in " ".join(_job().get("env", {})).lower()
    checkout = next(step for step in _job()["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_builds_payload_only_then_assembles_unsigned_release():
    text = _run_text()

    assert "deploy/image/build-native-payload.sh" in text
    assert "build-image.sh" not in text
    assert "--source-revision \"$GITHUB_SHA\"" in text
    assert "--lock \"$RESOLVED_LOCK\"" in text
    assert "deploy/image/resolve-build-lock.py" in text
    assert "install-pinky-hardware-deps.sh --lock \"$RESOLVED_LOCK\"" in text
    assert "deploy/release/build_payload_release.py build" in text
    assert "deploy/release/build_payload_release.py pack" in text and "--allow-unsigned" in text
    assert "test ! -e \"$release/SHA256SUMS.sig\"" in text
    assert "sha256sum --check" in text


def test_ros_apt_source_is_checksum_pinned_like_the_image_workflow():
    image = (ROOT / ".github" / "workflows" / "build-pinky-image.yml").read_text(encoding="utf-8")
    text = _run_text()
    # Public apt-source SHA-256 checksum: integrity data, not a credential.
    apt_source_sha256 = "0804d9b13db770eb87019be414cd78378835228ad5fa801fc88758596dd8f7e5"

    assert apt_source_sha256 in text and apt_source_sha256 in image
    assert "sha256sum --check --strict" in text


def test_uploads_unsigned_artifact_named_by_release_and_sha():
    upload = next(step for step in _job()["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))

    assert upload["with"]["name"] == (
        "rosy-native-payload-unsigned-${{ inputs.release_id }}-${{ github.sha }}")
    assert upload["with"]["if-no-files-found"] == "error"


def test_payload_records_the_ros_debs_it_was_built_against():
    # D-225 review: the payload builds against the runner's current ROS debs,
    # not the image's; ros-packages.txt lets the operator diff the two.
    script = (ROOT / "deploy" / "image" / "build-native-payload.sh").read_text(encoding="utf-8")
    deb = script.index('mv -f -- "$DEB_INVENTORY.tmp" "$DEB_INVENTORY"')
    ros = script.index("awk -F'\\t' '$1 ~ /^ros-jazzy-/ { print $1 \"=\" $2 }' \"$DEB_INVENTORY\"")
    assert deb < ros
    assert '"$RELEASE_ROOT/ros-packages.txt"' in script
    notes = (ROOT / "deploy" / "release" / "AGENTS.md").read_text(encoding="utf-8")
    assert "ros-packages.txt" in notes and "deb-packages.txt" in notes
