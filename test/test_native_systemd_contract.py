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
        "exec /opt/rosy/current/install/lib/core/core --ros-args", "Restart=on-failure",
        "KillSignal=SIGINT",
    ):
        assert directive in unit
    assert "DeviceAllow=" not in unit
    assert "docker" not in unit.lower()


def test_core_is_the_service_main_process_so_stop_signals_stay_clean():
    """The node itself is the unit's main process: systemd sees the real stop signal.

    Under `ros2 run` the wrapper re-encoded a signal death of the node as exit 241
    (SIGTERM) / 254 (SIGINT), so an ordinary stop in the window before core.main installs
    its handlers left the unit `failed` and, when the signal came from outside systemctl,
    restarted it 2 s later. Exec'ing the entry script removes that re-encoding (and the
    ros2 CLI's own startup window, and one Python process). Because systemd then counts a
    SIGINT/SIGTERM death of the main process as clean, core must not escalate a stuck
    shutdown by re-signalling itself — `core.main` exits with
    STUCK_SHUTDOWN_EXIT_CODE=2 so that stays visible as `Result=exit-code`.
    No SuccessExitStatus is added: nothing here needs remapping, and a remap would also
    whitewash that escalation.
    """
    unit = _read("rosy-core.service")
    exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))

    assert "ros2 run" not in exec_start
    assert "SuccessExitStatus" not in unit
    # the other half of the contract lives in core.main: the escalation must not be a
    # signal death, or systemd would count it as a clean stop like any other
    core_main = (ROOT / "src" / "core" / "core" / "core" / "main.py").read_text(
        encoding="utf-8")
    assert "STUCK_SHUTDOWN_EXIT_CODE = 2" in core_main
    assert "os._exit(STUCK_SHUTDOWN_EXIT_CODE)" in core_main
    assert "os.kill(os.getpid()" not in core_main
    # the hard-coded entry-script path only exists in a --merge-install payload
    payload = (ROOT / "deploy" / "image" / "build-native-payload.sh").read_text(encoding="utf-8")
    assert "--merge-install" in payload
    assert '--install-base "$INSTALL_ROOT"' in payload
    assert 'INSTALL_ROOT="$RELEASE_ROOT/install"' in payload
    setup_cfg = (ROOT / "src" / "core" / "core" / "setup.cfg").read_text(encoding="utf-8")
    assert "install_scripts=$base/lib/core" in setup_cfg
    # the script itself is generated from this entry point; a rename would leave a unit
    # pointing at a file nobody builds any more
    setup_py = (ROOT / "src" / "core" / "core" / "setup.py").read_text(encoding="utf-8")
    assert "'core=core.main:main'" in setup_py


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


def _load_probe(name="wait_core_ready_stop"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, NATIVE / "wait-core-ready.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_probe_treats_a_stop_signal_as_a_clean_exit():
    """`systemctl stop` during activation signals ExecStartPost as well.

    WSL systemd 2026-09-23: the probe died of SIGINT (KeyboardInterrupt) and the unit
    ended `failed` with Result=signal on every stop during startup, whatever core did.
    """
    import pytest

    probe = _read("wait-core-ready.py")
    main_block = probe[probe.index('if __name__ == "__main__":'):]
    assert "signal.SIGINT, signal.SIGTERM" in main_block
    assert main_block.index("signal.signal(") < main_block.index("sys.exit(main())")
    with pytest.raises(SystemExit) as exc:
        _load_probe()._stop_requested(2, None)
    assert exc.value.code == 0


def test_readiness_probe_process_exits_zero_on_sigint_and_sigterm():
    import os
    import signal
    import subprocess
    import sys
    import time

    import pytest

    if os.name != "posix":
        pytest.skip("POSIX signal delivery; covered by the handler test on Windows")
    for signum in (signal.SIGINT, signal.SIGTERM):
        env = dict(os.environ, ROSY_API_PORT="9", ROSY_CORE_READY_TIMEOUT_S="30")
        proc = subprocess.Popen([sys.executable, str(NATIVE / "wait-core-ready.py")], env=env,
                                stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        proc.send_signal(signum)
        _, err = proc.communicate(timeout=10)
        assert proc.returncode == 0, (signum, err)
        assert "stop requested" in err


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
