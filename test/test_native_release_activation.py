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
    from deploy.robot.pinky_pro.native.native_release import NativeReleaseManager

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
        root / "deploy/robot/pinky_pro/native/activate-release.sh",
        root / "deploy/robot/pinky_pro/native/rollback-release.sh",
        root / "deploy/robot/pinky_pro/native/native_release.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "curl " not in text
    assert "wget " not in text
    assert "docker " not in text.lower()
    assert "systemctl" in text
    assert "native_release.py" in paths[0].read_text(encoding="utf-8")


def test_artifact_gate_can_verify_the_signed_native_release_before_media_write():
    root = Path(__file__).resolve().parents[1]
    verifier = (root / "deploy/robot/pinky_pro/image/verify-artifacts.sh").read_text(encoding="utf-8")

    assert "ROSY_NATIVE_RELEASE_ID" in verifier
    # D-225 2.2: unsigned in the image; verified with the dist's factory signature.
    assert "verify-mounted-image.py" in verifier
    assert '--factory-dist "$DIST"' in verifier
    assert '--public-key "$NATIVE_PUBLIC_KEY"' in verifier
    mounted = (root / "deploy/robot/pinky_pro/image/verify-mounted-image.py").read_text(encoding="utf-8")
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


NATIVE_DIR = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "pinky_pro" / "native"


def _part_of_runtime_units() -> set[str]:
    return {
        unit.name for unit in NATIVE_DIR.iterdir()
        if unit.suffix == ".service"
        and "PartOf=rosy-runtime.target" in unit.read_text(encoding="utf-8").splitlines()
    }


def test_stopping_the_runtime_waits_for_every_unit_that_is_part_of_it(monkeypatch):
    # The target is ordered After= its PartOf units, so its own stop job ends at
    # once while CORE's stop job still waits behind io/camera (After=rosy-core).
    # systemctl waits only for the jobs it was asked for, and the start that
    # follows replaced CORE's pending stop with a no-op: CORE kept running the
    # old release after "activation" (9dfk, 2026-10-01).
    from deploy.robot.pinky_pro.native import native_release

    calls = []
    monkeypatch.setattr(native_release.subprocess, "run",
                        lambda argv, **kwargs: calls.append(argv))

    native_release.NativeReleaseManager._systemctl("stop")
    native_release.NativeReleaseManager._systemctl("start")

    stop, start = calls
    assert stop[:2] == ["systemctl", "stop"]
    assert set(stop[2:]) == {"rosy-runtime.target", *_part_of_runtime_units()}
    assert start == ["systemctl", "start", "rosy-runtime.target"]


def test_the_runtime_part_of_units_are_core_io_and_camera():
    # Guards the helper above against reading an empty directory.
    assert _part_of_runtime_units() == {"rosy-core.service", "rosy-io.service", "rosy-camera.service"}


# --- D-406 review N1: a precondition the activator runs right before stopping --------------


def test_a_refusing_precheck_stops_activation_before_the_runtime_stops(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    runtime = RuntimeRecorder()
    calls = []

    def precheck() -> None:
        calls.append("precheck")
        raise ValueError("NATIVE_PRECHECK_REFUSED: robot is moving")

    manager = manager_type(root=root, public_key=key, runtime=runtime, links=links, precheck=precheck)

    with pytest.raises(ValueError, match="NATIVE_PRECHECK_REFUSED"):
        manager.activate(first.name)

    assert calls == ["precheck"]
    assert runtime.actions == []
    assert links.values["current"] is None
    assert not (root / "var/lib/rosy/releases/native-activation.json").exists()


def test_the_precheck_runs_after_verification_and_before_the_stop(native_case):
    manager_type, root, key, _private, first, _second, links = native_case
    order = []
    runtime = RuntimeRecorder()

    def recording_runtime(action: str) -> None:
        order.append(action)
        runtime(action)

    manager = manager_type(root=root, public_key=key, runtime=recording_runtime, links=links,
                           precheck=lambda: order.append("precheck"))
    manager.activate(first.name)
    assert order == ["precheck", "stop", "start"]

    (first / "install/.rosy-release").write_text("tampered", encoding="utf-8")
    order.clear()
    links.values["current"] = None
    with pytest.raises(ValueError):
        manager.activate(first.name)
    assert order == []  # a release that does not verify never reaches the precheck


def test_the_precheck_command_comes_from_the_environment(monkeypatch):
    import sys

    from deploy.robot.pinky_pro.native.native_release import PRECHECK_ENV, _env_precheck

    python = sys.executable.replace("\\", "/")
    monkeypatch.delenv(PRECHECK_ENV, raising=False)
    assert _env_precheck() is None

    monkeypatch.setenv(PRECHECK_ENV, f'"{python}" -c "import sys; print(\'moving\'); sys.exit(3)"')
    with pytest.raises(ValueError, match="NATIVE_PRECHECK_REFUSED.*moving"):
        _env_precheck()()

    monkeypatch.setenv(PRECHECK_ENV, f'"{python}" -c "pass"')
    _env_precheck()()  # exit 0 passes


def test_the_cli_activation_runs_the_environment_precheck(native_case, monkeypatch, capsys):
    import sys

    from deploy.robot.pinky_pro.native import native_release

    _manager_type, root, key, _private, first, _second, _links = native_case
    python = sys.executable.replace("\\", "/")
    monkeypatch.setenv(native_release.PRECHECK_ENV, f'"{python}" -c "import sys; sys.exit(3)"')

    code = native_release._main(["--root", str(root), "--public-key", str(key),
                                 "activate", "--release-id", first.name])

    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 1
    assert result["ok"] is False and result["error"].startswith("NATIVE_PRECHECK_REFUSED")
    assert not (root / "opt/rosy/current").exists()


def test_only_the_precheck_busy_exit_is_a_refusal(monkeypatch):
    # Verification review M2: exit 3 is "robot busy"; any other exit is a failed precheck.
    import sys

    from deploy.robot.pinky_pro.native.native_release import PRECHECK_ENV, _env_precheck

    python = sys.executable.replace("\\", "/")
    monkeypatch.setenv(PRECHECK_ENV, f'"{python}" -c "import sys; sys.exit(1)"')
    with pytest.raises(ValueError, match="^NATIVE_PRECHECK_FAILED: exit 1"):
        _env_precheck()()
    monkeypatch.setenv(PRECHECK_ENV, f'"{python}" -c "import sys; sys.exit(3)"')
    with pytest.raises(ValueError, match="^NATIVE_PRECHECK_REFUSED"):
        _env_precheck()()
    monkeypatch.setenv(PRECHECK_ENV, '"/definitely/not/a/program"')
    with pytest.raises(ValueError, match="^NATIVE_PRECHECK_FAILED: precheck could not run"):
        _env_precheck()()


def test_a_precheck_that_hangs_times_out_as_failed(monkeypatch):
    # Verification review L6
    import sys

    from deploy.robot.pinky_pro.native import native_release

    python = sys.executable.replace("\\", "/")
    monkeypatch.setattr(native_release, "PRECHECK_TIMEOUT_S", 1)
    monkeypatch.setenv(native_release.PRECHECK_ENV, f'"{python}" -c "import time; time.sleep(30)"')
    with pytest.raises(ValueError, match="^NATIVE_PRECHECK_FAILED: precheck could not run"):
        native_release._env_precheck()()
