"""Contracts for installing native ROSY into the mounted Ubuntu Pi image."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy" / "image"
CUSTOMIZER = IMAGE / "customize-rootfs.sh"
VERIFY = IMAGE / "verify-mounted-image.py"


def test_ros_apt_source_package_is_exactly_pinned():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    ros = lock["ros"]
    assert ros["apt_source_version"] == "1.2.0"
    assert ros["apt_source_url"].endswith("/1.2.0/ros2-apt-source_1.2.0.noble_all.deb")
    assert ros["apt_source_sha256"] == "0804d9b13db770eb87019be414cd78378835228ad5fa801fc88758596dd8f7e5"


def test_customizer_installs_native_ros_and_never_product_docker():
    source = CUSTOMIZER.read_text(encoding="utf-8")
    build = (IMAGE / "build-image.sh").read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")

    assert "ros-jazzy-ros-base" in source
    assert "ros-jazzy-rmw-cyclonedds-cpp" in source
    assert "rosdep install" in source
    assert "chroot" in source
    assert "systemctl --root" in source
    assert "docker" not in source.lower()
    assert "--source-tree" in build and "--lock" in build
    assert "motion_profiles.yaml" in payload and "cyclonedds.xml" in payload


def test_customizer_materializes_all_locked_ubuntu_apt_sources_before_update():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert any("noble-updates" in item for item in lock["os"]["apt_sources"])
    assert 'lock["os"]["apt_sources"]' in source
    assert "rosy-ubuntu.list" in source
    assert source.index("rosy-ubuntu.list") < source.index('chroot "$ROOT" apt-get update')


def test_customizer_installs_only_required_product_package_dependency_closure():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert "resolve-required-source-paths.py" in source
    assert "ROSDEP_SOURCE_PATHS" in source
    assert '--source-root "$ROOT/tmp/rosy-src"' in source
    assert "--chroot-prefix /tmp/rosy-src" in source
    assert '"$ROOT/tmp/rosy-src/src"' not in source
    assert 'rosdep install --from-paths "${ROSDEP_SOURCE_PATHS[@]}"' in source
    assert "rosdep install --from-paths /tmp/rosy-src" not in source
    assert 'chroot "$ROOT" apt-get clean' in source


def test_customizer_installs_wiringpi_runtime_from_the_verified_lock():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    for fragment in (
        "hardware_dependencies", "wiringpi_url", "wiringpi_sha256",
        "sha256sum", "dpkg -i /tmp/wiringpi-arm64.deb",
    ):
        assert fragment in source
    assert source.index("sha256sum") < source.index("dpkg -i /tmp/wiringpi-arm64.deb")


def test_customizer_installs_and_enables_chrony():
    """CORE SRS §25: UTC ISO 8601 타임스탬프는 동기된 시계를 전제로 한다."""
    source = CUSTOMIZER.read_text(encoding="utf-8")
    verifier = VERIFY.read_text(encoding="utf-8")

    assert " chrony" in source  # apt install list
    assert "chrony.service" in source
    assert source.index("chrony.service") > source.index("enable")  # enabled, not just installed
    assert "chronyd" in verifier  # the mounted-image check exists too


def _valid_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    release = root / "opt/rosy/releases/2026.09.22-001"
    for path in (
        root / "opt/ros/jazzy",
        release / "install",
        root / "etc/systemd/system",
        root / "etc/rosy",
        root / "etc/rosy/trusted-release-keys",
        root / "opt/rosy/first-boot",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (root / "opt/ros/jazzy/setup.bash").write_text("# fixture\n", encoding="utf-8")
    (release / "install/setup.bash").write_text("# fixture\n", encoding="utf-8")
    (root / "opt/rosy/first-boot/rosy-first-boot.py").write_text("# fixture\n", encoding="utf-8")
    for runtime, names in (
        (root / "opt/rosy/native-runtime", ("native_release.py", "recover-release.sh", "signing.py")),
        (release / "deploy/robot/native", ("native_release.py", "signing.py")),
    ):
        runtime.mkdir(parents=True, exist_ok=True)
        for name in names:
            (runtime / name).write_text("# fixture\n", encoding="utf-8")
    (release / "required-ros-packages.txt").write_text(
        "# Mandatory product packages in every image.\ncore\ncontrol\n",
        encoding="utf-8",
    )
    (release / "rosy-packages.txt").write_text("control\ncore\n", encoding="utf-8")
    (root / "etc/rosy/motion_profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")
    (root / "etc/rosy/cyclonedds.xml").write_text("<CycloneDDS/>\n", encoding="utf-8")
    (root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem").write_text(
        "-----BEGIN PUBLIC KEY-----\nfixture\n-----END PUBLIC KEY-----\n",
        encoding="utf-8",
    )
    for unit in (
        "rosy-first-boot.service",
        "rosy-release-recover.service",
        "rosy-sd-provision.service",
        "rosy-core.service",
        "rosy-runtime.target",
    ):
        (root / "etc/systemd/system" / unit).write_text("[Unit]\n", encoding="utf-8")
    # chrony ships enabled (CORE SRS §25 premise, verifier-checked).
    (root / "usr/sbin").mkdir(parents=True, exist_ok=True)
    (root / "usr/sbin/chronyd").write_text("# fixture\n", encoding="utf-8")
    (root / "usr/sbin/dnsmasq").write_text("# fixture\n", encoding="utf-8")
    wants = root / "etc/systemd/system/multi-user.target.wants/chrony.service"
    wants.parent.mkdir(parents=True, exist_ok=True)
    wants.write_text("[Unit]\n", encoding="utf-8")
    # D-192 US-003: the post-runtime indicator run ships enabled.
    (root / "etc/systemd/system/rosy-boot-status-ready.service").write_text("[Unit]\n", encoding="utf-8")
    (wants.parent / "rosy-boot-status-ready.service").write_text("[Unit]\n", encoding="utf-8")
    return root


def _verify(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(root), "--release-id", "2026.09.22-001"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_mounted_image_verifier_accepts_native_core_only_layout(tmp_path):
    root = _valid_root(tmp_path)
    completed = _verify(root)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True


def test_mounted_image_verifier_rejects_missing_required_package(tmp_path):
    root = _valid_root(tmp_path)
    release = root / "opt/rosy/releases/2026.09.22-001"
    (release / "rosy-packages.txt").write_text("core\n", encoding="utf-8")
    completed = _verify(root)
    assert completed.returncode != 0
    assert "control" in completed.stderr


def test_mounted_image_verifier_rejects_product_docker_or_device_secrets(tmp_path):
    root = _valid_root(tmp_path)
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/docker").write_text("fixture\n", encoding="utf-8")
    (root / "etc/rosy/runtime.env").write_text("ROSY_NAMESPACE=rosy_01\n", encoding="utf-8")
    connections = root / "etc/NetworkManager/system-connections"
    connections.mkdir(parents=True)
    (connections / "secret.nmconnection").write_text(
        "psk=" + "secret\n", encoding="utf-8"
    )
    completed = _verify(root)
    assert completed.returncode != 0
    assert "docker" in completed.stderr.lower()
    assert "device-neutral" in completed.stderr.lower()


def test_mounted_image_verifier_rejects_missing_or_disabled_chrony(tmp_path):
    """CORE SRS §25: 타임스탬프 상관의 전제인 chrony 가 빠지거나 꺼진 이미지."""
    disabled = _valid_root(tmp_path)
    (disabled / "etc/systemd/system/multi-user.target.wants/chrony.service").unlink()
    completed = _verify(disabled)
    assert completed.returncode != 0
    assert "chrony" in completed.stderr.lower()

    absent = _valid_root(tmp_path)
    (absent / "usr/sbin/chronyd").unlink()
    completed = _verify(absent)
    assert completed.returncode != 0
    assert "chrony" in completed.stderr.lower()


def test_mounted_image_verifier_rejects_a_missing_or_disabled_ready_run(tmp_path):
    # D-192 US-003: without it CORE_READY waits for the 30 s timer.
    disabled = _valid_root(tmp_path / "disabled")
    (disabled / "etc/systemd/system/multi-user.target.wants/rosy-boot-status-ready.service").unlink()
    completed = _verify(disabled)
    assert completed.returncode != 0
    assert "rosy-boot-status-ready.service is not enabled" in completed.stderr

    absent = _valid_root(tmp_path / "absent")
    (absent / "etc/systemd/system/rosy-boot-status-ready.service").unlink()
    completed = _verify(absent)
    assert completed.returncode != 0
    assert "missing systemd unit: rosy-boot-status-ready.service" in completed.stderr


def test_customizer_executes_native_entrypoints_inside_the_image():
    # D-174 F5: file-existence checks passed an image whose recovery gate could
    # not import its helper. The customizer must run the installed copies.
    source = CUSTOMIZER.read_text(encoding="utf-8")

    probe = "rosy-native-probe"
    assert probe in source
    for runtime in ("/opt/rosy/native-runtime/native_release.py",
                    '/opt/rosy/releases/$RELEASE_ID/deploy/robot/native/native_release.py'):
        assert f'chroot "$ROOT" python3 -B {runtime}' in source
    assert 'chroot "$ROOT" python3 -B /opt/rosy/first-boot/rosy-first-boot.py --help' in source
    assert source.index("rosy-native-probe") < source.index("verify-mounted-image.py")


def test_image_enables_and_probes_the_d176_boot_settings_and_fallback_ap():
    # D-176: the settings file and the fallback AP only exist on a device if the
    # image carries, enables and can import them where it installs them.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    enable = source[source.index("systemctl --root"):source.index("mkdir -p \"$ROOT/etc/issue.d\"")]
    for unit in ("rosy-config.service", "rosy-network.service"):
        assert unit in enable, unit
    assert "rosy-config-apply.py rosy-network.py" in source
    assert 'chroot "$ROOT" python3 -B "/opt/rosy/native-runtime/$entrypoint" --help' in source

    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    for line in ('cp "$NATIVE_RUNTIME_SOURCE/rosy-config.service" "$OVERLAY/etc/systemd/system/"',
                 'cp "$NATIVE_RUNTIME_SOURCE/rosy-network.service" "$OVERLAY/etc/systemd/system/"',
                 'cp "$NATIVE_RUNTIME_SOURCE/defaults.yaml" "$OVERLAY/etc/rosy/defaults.yaml"'):
        assert line in payload, line


def test_image_puts_rosy_diag_on_path():
    # D-175 L2: an operator on the console types `rosy-diag collect`.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    assert 'ln -sfn /opt/rosy/native-runtime/rosy-diag "$ROOT/usr/local/bin/rosy-diag"' in source


def test_the_image_carries_dnsmasq_for_the_fallback_ap(tmp_path):
    # D-176 review: dnsmasq-base is only a Recommends of network-manager, and
    # the customizer installs with --no-install-recommends.
    assert "dnsmasq-base" in CUSTOMIZER.read_text(encoding="utf-8")
    root = _valid_root(tmp_path)
    (root / "usr/sbin/dnsmasq").unlink()

    completed = _verify(root)

    assert completed.returncode != 0
    assert "dnsmasq" in completed.stdout + completed.stderr


# --- D-189: CORE's Python runtime is a hash-locked input, imported in-image ---

REQUIREMENTS = IMAGE / "device-python-requirements.txt"
PROBE = IMAGE / "probe-core-runtime.py"
# The set that was hotfixed onto the first 2026.09.23-005 card and runs on the
# WSL sim box. Changing one of these is a runtime change, not a refresh.
TOP_LEVEL_PINS = {
    "pydantic": "2.13.5", "pydantic-core": "2.46.5", "fastapi": "0.141.1",
    "starlette": "1.6.0", "uvicorn": "0.52.4", "websockets": "17.1",
}
# What fastapi 0.141.1, starlette 1.6.0, uvicorn 0.52.4 and pydantic 2.13.5
# require on CPython 3.12 (no extras), resolved 2026-09-24.
CLOSURE = {"annotated-doc", "annotated-types", "anyio", "click", "h11", "idna",
           "typing-extensions", "typing-inspection"}
# Distributions with compiled wheels need one hash per platform.
PLATFORM_WHEELS = {"pydantic-core", "websockets"}


def _requirements() -> dict[str, tuple[str, list[str]]]:
    entries: dict[str, tuple[str, list[str]]] = {}
    text = REQUIREMENTS.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement, *options = line.split()
        name, version = requirement.split("==")
        hashes = [option.split(":", 1)[1] for option in options if option.startswith("--hash=sha256:")]
        assert len(hashes) == len(options), line
        entries[name] = (version, hashes)
    return entries


def _probe_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("probe_core_runtime", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_python_runtime_is_pinned_and_hash_locked_for_both_platforms():
    entries = _requirements()

    assert set(entries) == set(TOP_LEVEL_PINS) | CLOSURE
    for name, version in TOP_LEVEL_PINS.items():
        assert entries[name][0] == version, name
    for name, (version, hashes) in entries.items():
        assert version and all(c.isdigit() or c == "." for c in version), name
        assert hashes and all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in hashes), name
        assert len(set(hashes)) == len(hashes), name
        assert len(hashes) == (2 if name in PLATFORM_WHEELS else 1), name


def test_the_input_lock_pins_the_requirements_file_bytes():
    import hashlib

    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    runtime = lock["python_runtime"]
    data = REQUIREMENTS.read_bytes()

    assert runtime["requirements"] == REQUIREMENTS.name
    assert b"\r" not in data, "the lock pins LF bytes (.gitattributes eol=lf)"
    assert hashlib.sha256(data).hexdigest() == runtime["requirements_sha256"]
    assert runtime["pydantic_major"] == 2
    assert runtime["verified"] is True
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "deploy/image/device-python-requirements.txt text eol=lf" in attributes


def test_customizer_installs_the_locked_runtime_after_rosdep():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert "python3-pip" in source[source.index("apt-get install -y"):source.index("rosdep init")]
    assert "lock_value python_runtime requirements_sha256" in source
    assert "CORE Python requirements do not match inputs.lock.yaml" in source
    install = source.index('chroot "$ROOT" python3 -m pip install')
    command = source[install:source.index("|| fail", install)]
    for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:", "--ignore-installed",
                 "--break-system-packages", "-r /tmp/rosy-core-probe/device-python-requirements.txt"):
        assert flag in command, flag
    # Debian's posix_prefix scheme would install to site-packages, off sys.path.
    assert "--prefix" not in command and "--target" not in command and "--user" not in command
    # rosdep installs apt pydantic 1.10 first; the lock must win after it.
    assert source.index("rosdep install --from-paths") < install
    # Readable by the service users whatever the builder's umask is.
    assert source[source.rindex("\n", 0, install):install].endswith("(umask 022 && ")


def test_image_and_release_record_the_same_python_runtime():
    # D-189 review: the runtime lives in the image, the release names the one it
    # needs, and native_release.py refuses a mismatch on activate and rollback.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")

    assert '"$ROOT/usr/local/share/rosy/python-runtime.sha256"' in source
    assert 'printf \'%s\\n\' "$PYTHON_REQUIREMENTS_SHA"' in source
    assert "release python-runtime.sha256 does not match" in source
    assert 'sha256sum "$SCRIPT_DIR/device-python-requirements.txt"' in payload
    assert '"$RELEASE_ROOT/python-runtime.sha256"' in payload
    native = (ROOT / "deploy/robot/native/native_release.py").read_text(encoding="utf-8")
    assert 'PYTHON_RUNTIME_IMAGE_FILE = Path("usr/local/share/rosy/python-runtime.sha256")' in native
    assert 'PYTHON_RUNTIME_RELEASE_FILE = "python-runtime.sha256"' in native


def test_customizer_fails_the_build_when_core_does_not_import_in_the_image():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    probe = source.index("probe-core-runtime.py --requirements")
    call = source[source.rindex("chroot", 0, probe):source.index("\n", source.index("|| fail", probe))]
    assert "source /opt/ros/jazzy/setup.bash" in call
    assert "source /opt/rosy/current/install/setup.bash" in call
    assert "python3 -B" in call and "PYTHONDONTWRITEBYTECODE=1" in call
    # As the unit runs it (D-189 review): the service user, its HOME, no login
    # shell, no user site, and runtime.env when the image has one.
    assert "setpriv --reuid=rosy-core --regid=rosy-core --clear-groups" in call
    assert "HOME=/var/lib/rosy/core" in call and "PYTHONNOUSERSITE=1" in call
    assert "bash --noprofile --norc -c" in call and "bash -lc" not in call
    assert "if [ -r /etc/rosy/runtime.env ]; then . /etc/rosy/runtime.env; fi" in call
    # The accounts exist before the probe switches to one.
    assert source.index("useradd --uid 960") < probe
    assert '|| fail "CORE does not import inside the image"' in call
    # After the release is linked as current, before the image is accepted.
    assert source.index('ln -s "releases/$RELEASE_ID" "$ROOT/opt/rosy/current"') < probe
    assert probe < source.index("verify-mounted-image.py")


def test_ci_tests_against_the_runtime_the_device_runs():
    for workflow in ("ci.yml", "arm64-rehearsal.yml"):
        text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
        lock = "--require-hashes --no-deps --only-binary=:all: -r deploy/image/device-python-requirements.txt"
        assert lock in text
        # Test tools come after the lock, constrained to its versions, so their
        # dependencies (anyio, h11, idna, typing-extensions) are not a second copy.
        constraints = "grep -o '^[A-Za-z0-9._-]*==[^ ]*' deploy/image/device-python-requirements.txt"
        assert constraints in text
        assert text.index(lock) < text.index(constraints) < text.index("-c /tmp/rosy-runtime-constraints.txt")
        for line in text.splitlines():
            if "pip" in line and " install" in line and "-r deploy/image" not in line:
                words = set(line.split())
                assert not words & {"pydantic", "fastapi", "starlette", "uvicorn", "websockets"}, (workflow, line)


def test_probe_reads_every_pin():
    pins = _probe_module().read_pins(REQUIREMENTS)
    assert pins == {name: version for name, (version, _hashes) in _requirements().items()}


def test_probe_follows_lazy_imports_of_the_core_entrypoints():
    probe = _probe_module()
    node = (ROOT / "src/core/core/core/node.py").read_text(encoding="utf-8")
    main = (ROOT / "src/core/core/core/main.py").read_text(encoding="utf-8")

    modules = set(probe.lazy_imports(node)) | set(probe.lazy_imports(main))
    # Function-level imports a flag-only --help never reaches.
    for name in ("uvicorn", "core_api_web.api.app", "core.bridge.ros_bridge",
                 "core_common.profile", "core.node", "core_common.config", "rclpy"):
        assert name in modules, name
    assert "__future__" not in modules


def test_probe_skips_imports_guarded_by_try():
    source = (
        "import json\n"
        "def f():\n"
        "    import uvicorn\n"
        "    try:\n"
        "        from slam_toolbox.srv import SaveMap\n"
        "    except ImportError:\n"
        "        import fallback_only\n"
    )
    modules = _probe_module().lazy_imports(source)
    assert "uvicorn" in modules and "json" in modules
    assert "slam_toolbox.srv" not in modules and "slam_toolbox.srv.SaveMap" not in modules


def test_probe_fails_on_a_missing_or_wrong_pin(tmp_path, capsys):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "rosy-no-such-distribution==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")

    assert _probe_module().main(["--requirements", str(requirements)]) == 1
    assert "rosy-no-such-distribution: not installed" in capsys.readouterr().err
