"""Contracts for the D-225 2.1 native payload-only workflow."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-native-payload.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job():
    return _workflow()["jobs"]["build-unsigned-payload"]


PREREQS = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "payload-builder" / "install-ros-build-prereqs.sh"


def _run_text() -> str:
    return "\n".join(step.get("run", "") for step in _job()["steps"])


def _ros_install_text() -> str:
    """D-553 addendum 3: the ROS prerequisites moved into the payload-builder image script."""
    return PREREQS.read_text(encoding="utf-8")


def test_manual_native_arm64_and_read_only():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    job = _job()

    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["release_id"]["required"] is True
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert job.get("continue-on-error") is not True
    # packages: read pulls the payload-builder image (D-553 addendum 3); nothing writes.
    assert workflow["permissions"] == {"contents": "read", "packages": "read"}


def test_no_secrets_and_no_signing_in_ci():
    rendered = WORKFLOW.read_text(encoding="utf-8")

    assert "secrets." not in rendered
    assert "sign_image_release" not in _run_text()
    assert "private" not in " ".join(_job().get("env", {})).lower()
    checkout = next(step for step in _job()["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_builds_payload_only_then_assembles_unsigned_release():
    text = _run_text()

    assert "deploy/robot/pinky_pro/image/build-native-payload.sh" in text
    assert "build-image.sh" not in text
    assert "--source-revision \"$GITHUB_SHA\"" in text
    assert "--lock \"$RESOLVED_LOCK\"" in text
    assert "deploy/robot/pinky_pro/image/resolve-build-lock.py" in text
    assert "install-pinky-hardware-deps.sh --lock \"$RESOLVED_LOCK\"" in text
    assert "deploy/robot/pinky_pro/release/build_payload_release.py build" in text
    assert "deploy/robot/pinky_pro/release/build_payload_release.py pack" in text and "--allow-unsigned" in text
    assert "test ! -e \"$release/SHA256SUMS.sig\"" in text
    assert "sha256sum --check" in text


def test_ros_apt_source_is_checksum_pinned_like_the_image_workflow():
    image = (ROOT / ".github" / "workflows" / "build-pinky-image.yml").read_text(encoding="utf-8")
    text = _ros_install_text()
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
    script = (ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "build-native-payload.sh").read_text(encoding="utf-8")
    deb = script.index('mv -f -- "$DEB_INVENTORY.tmp" "$DEB_INVENTORY"')
    ros = script.index("awk -F'\\t' '$1 ~ /^ros-jazzy-/ { print $1 \"=\" $2 }' \"$DEB_INVENTORY\"")
    assert deb < ros
    assert '"$RELEASE_ROOT/ros-packages.txt"' in script
    notes = (ROOT / "deploy" / "robot" / "pinky_pro" / "release" / "AGENTS.md").read_text(encoding="utf-8")
    assert "ros-packages.txt" in notes and "deb-packages.txt" in notes


def test_ros_is_installed_from_the_image_locks_snapshot():
    """D-482: payload ROS comes from the lock's dated snapshot, no date literal in the workflow."""
    lock = yaml.safe_load(
        (ROOT / "deploy/robot/pinky_pro/image/inputs.lock.yaml").read_text(encoding="utf-8-sig")
    )
    url = lock["ros"]["apt_snapshot_url"]
    text = _ros_install_text()

    assert url.startswith("http://snapshots.ros.org/jazzy/") and url.endswith("/ubuntu")
    assert "['ros']['apt_snapshot_url']" in text
    assert "ros2.sources" in text
    assert "snapshots.ros.org/jazzy/20" not in WORKFLOW.read_text(encoding="utf-8") + text
    assert text.index("apt_snapshot_url") < text.index("ros-jazzy-ros-base")


def test_snapshot_signing_key_is_pinned_by_fingerprint_and_scoped():
    """D-482 addendum: the snapshot key is fetched by full fingerprint, checked, and trusted for the snapshot source only."""
    lock = yaml.safe_load(
        (ROOT / "deploy/robot/pinky_pro/image/inputs.lock.yaml").read_text(encoding="utf-8-sig")
    )
    key_fingerprint = lock["ros"]["apt_snapshot_key_fingerprint"]
    text = _ros_install_text()
    rendered = WORKFLOW.read_text(encoding="utf-8") + text
    keyring = "/etc/apt/keyrings/ros-snapshots-archive-keyring.gpg"

    # ROS 2 docs "Snapshot repository": 4B63 CF8F DE49 746E 98FA 01DD AD19 BAB3 CBF1 25EA.
    assert key_fingerprint == "4B63CF8FDE49746E98FA01DDAD19BAB3CBF125EA"
    assert "['ros']['apt_snapshot_key_fingerprint']" in text
    assert key_fingerprint not in rendered  # single source: the lock
    assert "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${ros_snapshot_key_fpr}" in text
    assert "gpg --dearmor" in text and f"ros_snapshot_keyring={keyring}" in text
    # The fetched key must be exactly the pinned fingerprint, or the job stops.
    assert 'gpg --show-keys --with-colons "$ros_snapshot_keyring"' in text
    assert '[[ "$ros_snapshot_key_got" != "$ros_snapshot_key_fpr" ]]' in text
    check = text.index('"$ros_snapshot_key_got" != "$ros_snapshot_key_fpr"')
    assert "exit 1" in text[check:check + 300]
    # Scoped trust: Signed-By on the snapshot stanza, live stanza removed, no global trust.
    assert "Signed-By: %s" in text
    assert "rm -f /etc/apt/sources.list.d/ros2.sources" in text
    assert 'grep -qx "Signed-By: $ros_snapshot_keyring"' in text
    assert "apt-key" not in rendered
    assert "trusted.gpg.d" not in rendered
    assert "trusted=yes" not in rendered.lower()
    assert "allow-insecure" not in rendered.lower()
    assert "allowunauthenticated" not in rendered.lower()
    assert check < text.index("ros-jazzy-ros-base")


def test_the_job_runs_in_the_builder_image_pinned_by_digest():
    """D-553 addendum 3: the prerequisites are a cached image, pulled read-only by digest."""
    workflow = _workflow()
    job = _job()
    default = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]["builder_image"]["default"]
    assert job["container"]["image"] == "${{ inputs.builder_image }}"
    assert job["container"]["credentials"]["password"] == "${{ github.token }}"
    assert default.startswith("ghcr.io/robotics-team-1213/rosy-payload-builder@sha256:")
    text = _run_text()
    assert "rosy-payload-builder@sha256:[0-9a-f]{64}$" in text  # a tag or another image stops the job
    assert text.index('[[ "$BUILDER_IMAGE" =~') < text.index("build-native-payload.sh")
    builder = (ROOT / ".github" / "workflows" / "build-payload-builder.yml").read_text(encoding="utf-8")
    assert "payload-builder/make-builder-image.sh" in builder and "secrets." not in builder
    make = (PREREQS.parent / "make-builder-image.sh").read_text(encoding="utf-8")
    assert "ubuntu@sha256:" in make and "install-ros-build-prereqs.sh" in make
