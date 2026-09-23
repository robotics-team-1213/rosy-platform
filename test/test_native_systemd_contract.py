"""D-161 native systemd runtime and privilege-boundary contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "native"


def _read(name: str) -> str:
    return (NATIVE / name).read_text(encoding="utf-8")


def test_native_runtime_files_exist():
    for name in (
        "rosy-core.service", "rosy-io.service", "rosy-navigation.service",
        "rosy-runtime.target", "rosy-runtime.env", "rosy-sd-provision.service",
        "rosy-release-recover.service", "recover-release.sh",
        "activate-release.sh", "rollback-release.sh", "native_release.py",
        "wait-core-ready.py",
    ):
        assert (NATIVE / name).is_file(), name


def test_core_runs_as_a_device_free_hardened_service():
    unit = _read("rosy-core.service")

    for directive in (
        "User=rosy-core", "Group=rosy-core",
        "EnvironmentFile=/etc/rosy/runtime.env",
        "DevicePolicy=closed", "PrivateDevices=true",
        "NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true",
        "ExecStartPost=/usr/bin/python3 /opt/rosy/current/deploy/robot/native/wait-core-ready.py",
        "ros2 run core core", "Restart=on-failure",
    ):
        assert directive in unit
    assert "DeviceAllow=" not in unit
    assert "docker" not in unit.lower()


def test_io_has_only_enumerated_devices_and_keeps_the_deadman_argument():
    unit = _read("rosy-io.service")

    for directive in (
        "User=rosy-io", "Group=rosy-io",
        "SupplementaryGroups=dialout i2c video gpio spi",
        "DevicePolicy=closed", "DeviceAllow=/dev/rosy-motor rw",
        "DeviceAllow=/dev/ttyAMA0 rw", "DeviceAllow=/dev/i2c-1 rw",
        "DeviceAllow=/dev/video0 rw", "rosy-core.service",
        "ros2 launch bringup bringup_robot.launch.py",
        "cmd_vel_timeout_s:=${ROSY_CMD_VEL_TIMEOUT_S}",
        "Conflicts=rosy-navigation.service", "Restart=on-failure",
    ):
        assert directive in unit
    assert "privileged" not in unit.lower()
    assert "docker" not in unit.lower()


def test_navigation_is_disabled_until_both_hardware_approvals_exist():
    unit = _read("rosy-navigation.service")

    for directive in (
        "ConditionPathExists=/etc/rosy/approvals/hardware.approved",
        "ConditionPathExists=/etc/rosy/approvals/navigation.approved",
        "Conflicts=rosy-io.service", "DevicePolicy=closed",
        "ros2 launch navigation hardware.launch.py",
        "cmd_vel_timeout_s:=${ROSY_CMD_VEL_TIMEOUT_S}",
    ):
        assert directive in unit
    assert "WantedBy=rosy-runtime.target" not in unit


def test_default_target_starts_core_only_after_recovery_and_provisioning():
    target = _read("rosy-runtime.target")

    assert "Requires=rosy-release-recover.service rosy-sd-provision.service" in target
    assert "Requires=rosy-core.service" in target
    assert "rosy-io.service" not in target
    assert "rosy-navigation.service" not in target
    assert "WantedBy=multi-user.target" in target


def test_native_recovery_is_a_required_fail_closed_boot_gate():
    unit = _read("rosy-release-recover.service")
    script = _read("recover-release.sh")

    for directive in (
        "DefaultDependencies=no", "After=local-fs.target", "Before=rosy-core.service rosy-runtime.target",
        "Type=oneshot", "RemainAfterExit=yes",
        "ExecStart=/opt/rosy/native-runtime/recover-release.sh",
    ):
        assert directive in unit
    assert "Restart=" not in unit
    assert "|| true" not in unit
    assert "native_release.py" in script
    assert " recover" in script
    assert "docker" not in (unit + script).lower()


def test_provisioning_gate_refuses_an_unpersonalized_device():
    unit = _read("rosy-sd-provision.service")

    assert "AssertPathExists=/var/lib/rosy/provisioning/complete.json" in unit
    assert "ExecStart=/usr/bin/test -s /var/lib/rosy/provisioning/complete.json" in unit
    assert "Before=rosy-core.service rosy-runtime.target" in unit


def test_runtime_environment_contains_no_secret_and_preserves_dds_isolation():
    env = _read("rosy-runtime.env")

    for name in (
        "ROS_DOMAIN_ID=", "ROSY_NAMESPACE=", "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp",
        "CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml",
        "ROSY_CMD_VEL_TIMEOUT_S=0.5", "ROSY_RUNTIME_MODE=core",
    ):
        assert name in env
    for forbidden in ("PASSWORD", "PASSPHRASE", "PSK", "TOKEN", "wifi_passphrase="):
        assert forbidden not in env.upper()


def test_readiness_probe_has_a_bounded_failure():
    probe = _read("wait-core-ready.py")

    # The port comes from ROSY_API_PORT (falls back to 8080) — a hardcoded
    # URL would fight a robot whose api_port overlay is not 8080.
    assert "ROSY_API_PORT" in probe
    assert '"8080"' in probe
    assert '"http://127.0.0.1:8080/api/v1"' not in probe
    assert "time.monotonic()" in probe
    assert "return 1" in probe
    assert "sys.exit(main())" in probe


def test_readiness_probe_honors_rosy_api_port():
    import importlib.util

    def _url_with_env(env_port):
        spec = importlib.util.spec_from_file_location(
            f"wait_core_ready_{env_port}", NATIVE / "wait-core-ready.py")
        module = importlib.util.module_from_spec(spec)
        import os
        old = os.environ.pop("ROSY_API_PORT", None)
        if env_port is not None:
            os.environ["ROSY_API_PORT"] = env_port
        try:
            spec.loader.exec_module(module)
        finally:
            if env_port is not None:
                os.environ.pop("ROSY_API_PORT", None)
            if old is not None:
                os.environ["ROSY_API_PORT"] = old
        return module.URL

    assert _url_with_env("8123") == "http://127.0.0.1:8123/api/v1"
    assert _url_with_env(None) == "http://127.0.0.1:8080/api/v1"


@pytest.mark.parametrize(
    ("unit_name", "log_dir"),
    [("rosy-core.service", "rosy-core"), ("rosy-io.service", "rosy-io"),
     ("rosy-navigation.service", "rosy-navigation")],
)
def test_ros_services_get_a_writable_ros_home_under_protect_home(unit_name, log_dir):
    # D-174 F6: service users have no home and ProtectHome=true; rclpy would try
    # $HOME/.ros/log and fail to initialize logging.
    unit = _read(unit_name)

    assert f"LogsDirectory={log_dir}" in unit
    assert f"Environment=ROS_HOME=/var/log/{log_dir} ROS_LOG_DIR=/var/log/{log_dir}" in unit
    assert "ProtectHome=true" in unit


def test_journald_keeps_a_bounded_persistent_ledger():
    # D-175 L0: the journal is the ledger every other diagnostic layer reads.
    conf = (ROOT / "deploy/robot/native/journald-60-rosy.conf").read_text(encoding="utf-8")
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")

    for directive in ("[Journal]", "Storage=persistent", "SystemMaxUse=200M", "RuntimeMaxUse=32M"):
        assert directive in conf
    assert 'journald-60-rosy.conf" "$OVERLAY/etc/systemd/journald.conf.d/60-rosy.conf"' in payload


def test_ros_log_directories_are_aged_out():
    # Review M9: ROS writes new files on every start, outside journald's cap.
    rules = (ROOT / "deploy/robot/native/tmpfiles-rosy-logs.conf").read_text(encoding="utf-8")
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")

    for name in ("rosy-core", "rosy-io", "rosy-navigation"):
        assert f"e /var/log/{name} - - - 7d" in rules
    assert 'tmpfiles-rosy-logs.conf" "$OVERLAY/etc/tmpfiles.d/rosy-logs.conf"' in payload


def test_boot_settings_apply_before_the_network_and_never_block_the_boot():
    # D-176: root oneshot outside CORE; the fallback AP reads what it wrote.
    unit = _read("rosy-config.service")

    for directive in (
        "Type=oneshot", "RemainAfterExit=yes",
        "ExecStart=/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-config-apply.py",
        "After=local-fs.target rosy-first-boot.service NetworkManager.service",
        "Before=network-online.target rosy-network.service",
        "WantedBy=multi-user.target",
    ):
        assert directive in unit, directive
    assert "User=" not in unit
    assert "After=NetworkManager.service rosy-config.service" in _read("rosy-network.service")
