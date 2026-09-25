from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from signing import build_sha256sums, sha256_file, sign_checksums


def _keys(tmp_path: Path) -> tuple[Path, Path]:
    private = tmp_path / "test.key"
    public = tmp_path / "rosy-native-test.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


# D-189: sha256 of the CORE Python requirements lock a release was built against.
IMAGE_RUNTIME = "1" * 64
OTHER_RUNTIME = "2" * 64


def _release(root: Path, private: Path, release_id: str, *, architecture="arm64",
             python_runtime: str | None = IMAGE_RUNTIME) -> Path:
    release = root / "opt" / "rosy" / "releases" / release_id
    files = {
        "install/.rosy-release": release_id,
        "deploy/robot/native/rosy-runtime.target": "[Unit]\nDescription=test\n",
        "rosy-packages.txt": "core\ninterfaces\n",
        "source-revision.txt": "a" * 40 + "\n",
    }
    if python_runtime is not None:
        files["python-runtime.sha256"] = python_runtime + "\n"
    for relative, content in files.items():
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "git_revision": "a" * 40,
        "target": {
            "board": "pinky_pro",
            "host": "raspberry-pi-5",
            "architecture": architecture,
            "os_family": "ubuntu-server",
            "os_release": "24.04",
        },
        "runtime": {"model": "native-systemd", "default_mode": "core"},
        "signing_key_id": "rosy-native-test",
        "files": [
            {"path": name, "sha256": sha256_file(release / name)}
            for name in sorted(files)
        ],
    }
    (release / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    paths = ["manifest.json", *sorted(files)]
    sums = build_sha256sums(release, paths)
    (release / "SHA256SUMS").write_bytes(sums)
    (release / "SHA256SUMS.sig").write_text(
        sign_checksums(sums, private), encoding="utf-8"
    )
    return release


class RuntimeRecorder:
    def __init__(self, *, fail_start_once: bool = False) -> None:
        self.actions: list[str] = []
        self.fail_start_once = fail_start_once

    def __call__(self, action: str) -> None:
        self.actions.append(action)
        if action == "start" and self.fail_start_once:
            self.fail_start_once = False
            raise RuntimeError("candidate did not become healthy")


class MemoryLinks:
    def __init__(self) -> None:
        self.values = {"current": None, "previous": None}

    def get(self, name: str) -> str | None:
        return self.values[name]

    def set(self, name: str, release_id: str | None) -> None:
        self.values[name] = release_id


@pytest.fixture
def native_case(tmp_path: Path):
    from deploy.robot.native.native_release import NativeReleaseManager

    private, public = _keys(tmp_path)
    root = tmp_path / "device"
    key = root / "etc" / "rosy" / "trusted-release-keys" / public.name
    key.parent.mkdir(parents=True)
    key.write_bytes(public.read_bytes())
    marker = root / "usr" / "local" / "share" / "rosy" / "python-runtime.sha256"
    marker.parent.mkdir(parents=True)
    marker.write_text(IMAGE_RUNTIME + "\n", encoding="utf-8")
    first = _release(root, private, "2026.09.22-001")
    second = _release(root, private, "2026.09.22-002")
    return NativeReleaseManager, root, key, private, first, second, MemoryLinks()


def test_activation_verifies_signature_and_switches_current_atomically(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    runtime = RuntimeRecorder()
    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links)

    outcome = manager.activate(first.name)

    assert outcome == {"ok": True, "release_id": first.name, "previous": None}
    assert links.values["current"] == first.name
    assert runtime.actions == ["stop", "start"]
    assert not (root / "var/lib/rosy/releases/native-activation.json").exists()


def test_unsigned_or_modified_release_is_refused_before_runtime_stops(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    (first / "install/.rosy-release").write_text("tampered", encoding="utf-8")
    runtime = RuntimeRecorder()
    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links)

    with pytest.raises(ValueError, match="CHECKSUM_MISMATCH"):
        manager.activate(first.name)

    assert runtime.actions == []
    assert links.values["current"] is None


def test_wrong_architecture_is_refused(native_case):
    manager_type, root, key, private, _first, _second, links = native_case
    wrong = _release(root, private, "2026.09.22-003", architecture="amd64")

    with pytest.raises(ValueError, match="architecture"):
        manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links).activate(wrong.name)


def test_failed_candidate_health_rolls_back_to_last_accepted_release(native_case):
    manager_type, root, key, _private, first, second, links = native_case
    manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links).activate(first.name)
    runtime = RuntimeRecorder(fail_start_once=True)
    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links)

    with pytest.raises(RuntimeError, match="rolled back"):
        manager.activate(second.name)

    assert links.values == {"current": first.name, "previous": second.name}
    assert runtime.actions == ["stop", "start", "stop", "start"]


def test_explicit_rollback_reverifies_previous_and_swaps_links(native_case):
    manager_type, root, key, _private, first, second, links = native_case
    manager = manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links)
    manager.activate(first.name)
    manager.activate(second.name)
    runtime = RuntimeRecorder()
    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links)

    outcome = manager.rollback()

    assert outcome["release_id"] == first.name
    assert links.values == {"current": first.name, "previous": second.name}
    assert runtime.actions == ["stop", "start"]


def test_power_loss_recovery_restores_the_prepared_old_release(native_case):
    manager_type, root, key, _private, first, second, links = native_case
    manager = manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links)
    manager.activate(first.name)
    journal = root / "var/lib/rosy/releases/native-activation.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({
        "schema_version": 1,
        "operation": "activate",
        "candidate": second.name,
        "old_current": first.name,
        "old_previous": None,
        "phase": "switched",
    }), encoding="utf-8")
    links.values["current"] = second.name

    outcome = manager.recover()

    assert outcome["recovered"] is True
    assert links.values["current"] == first.name
    assert not journal.exists()


def test_native_release_entrypoints_are_offline_and_container_free():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "deploy/robot/native/activate-release.sh",
        root / "deploy/robot/native/rollback-release.sh",
        root / "deploy/robot/native/native_release.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "curl " not in text
    assert "wget " not in text
    assert "docker " not in text.lower()
    assert "systemctl" in text
    assert "native_release.py" in paths[0].read_text(encoding="utf-8")


def test_artifact_gate_can_verify_the_signed_native_release_before_media_write():
    root = Path(__file__).resolve().parents[1]
    verifier = (root / "deploy/image/verify-artifacts.sh").read_text(encoding="utf-8")

    assert "ROSY_NATIVE_RELEASE_ID" in verifier
    # D-225 2.2: unsigned in the image; verified with the dist's factory signature.
    assert "verify-mounted-image.py" in verifier
    assert '--factory-dist "$DIST"' in verifier
    assert '--public-key "$NATIVE_PUBLIC_KEY"' in verifier
    mounted = (root / "deploy/image/verify-mounted-image.py").read_text(encoding="utf-8")
    assert "NativeReleaseManager(root=Path(scratch), public_key=public_key).verify(release_id)" in mounted


# --- D-189: a release must match the image's CORE Python runtime -----------

def test_release_built_for_another_python_runtime_is_refused_before_runtime_stops(native_case):
    manager_type, root, key, private, _first, _second, links = native_case
    other = _release(root, private, "2026.09.22-003", python_runtime=OTHER_RUNTIME)
    runtime = RuntimeRecorder()
    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links)

    with pytest.raises(ValueError, match="needs Python runtime 2{64}.*reflash with a matching image"):
        manager.activate(other.name)

    assert runtime.actions == []
    assert links.values["current"] is None
    assert not (root / "var/lib/rosy/releases/native-activation.json").exists()


def test_release_without_a_declared_python_runtime_is_refused(native_case):
    manager_type, root, key, private, _first, _second, links = native_case
    legacy = _release(root, private, "2026.09.22-003", python_runtime=None)

    with pytest.raises(ValueError, match="NATIVE_PYTHON_RUNTIME: .*does not declare"):
        manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links).activate(legacy.name)


def test_image_without_a_recorded_python_runtime_refuses_every_release(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    (root / "usr/local/share/rosy/python-runtime.sha256").unlink()

    with pytest.raises(ValueError, match="this image has none recorded"):
        manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links).activate(first.name)


def test_python_runtime_file_is_covered_by_the_release_signature(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    (first / "python-runtime.sha256").write_text(OTHER_RUNTIME + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CHECKSUM_MISMATCH"):
        manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links).activate(first.name)


def test_rollback_to_a_release_for_another_python_runtime_is_refused(native_case):
    manager_type, root, key, _private, first, second, links = native_case
    manager = manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links)
    manager.activate(first.name)
    manager.activate(second.name)
    marker = root / "usr/local/share/rosy/python-runtime.sha256"
    marker.write_text(OTHER_RUNTIME + "\n", encoding="utf-8")
    runtime = RuntimeRecorder()

    with pytest.raises(ValueError, match="needs Python runtime 1{64}"):
        manager_type(root=root, public_key=key, runtime=runtime, links=links).rollback()

    assert runtime.actions == []
    assert links.values == {"current": second.name, "previous": first.name}


def test_recovery_never_holds_on_the_python_runtime(native_case):
    # Recovery restores the release that was running; refusing it would leave
    # the device with no current release at all.
    manager_type, root, key, _private, first, second, links = native_case
    manager = manager_type(root=root, public_key=key, runtime=RuntimeRecorder(), links=links)
    manager.activate(first.name)
    (root / "usr/local/share/rosy/python-runtime.sha256").unlink()
    journal = root / "var/lib/rosy/releases/native-activation.json"
    journal.write_text(json.dumps({
        "schema_version": 1, "operation": "activate", "candidate": second.name,
        "old_current": first.name, "old_previous": None, "phase": "switched",
    }), encoding="utf-8")

    assert manager.recover()["recovered"] is True
    assert links.values["current"] == first.name
