"""D-161 native systemd runtime and privilege-boundary contracts."""

from __future__ import annotations

from pathlib import Path
import re

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
    core_main = (ROOT / "src" / "runtime" / "gateway" / "core" / "main.py").read_text(
        encoding="utf-8")
    assert "STUCK_SHUTDOWN_EXIT_CODE = 2" in core_main
    assert "os._exit(STUCK_SHUTDOWN_EXIT_CODE)" in core_main
    assert "os.kill(os.getpid()" not in core_main
    # the hard-coded entry-script path only exists in a --merge-install payload
    payload = (ROOT / "deploy" / "image" / "build-native-payload.sh").read_text(encoding="utf-8")
    assert "--merge-install" in payload
    assert '--install-base "$INSTALL_ROOT"' in payload
    assert 'INSTALL_ROOT="$RELEASE_ROOT/install"' in payload
    setup_cfg = (ROOT / "src" / "runtime" / "gateway" / "setup.cfg").read_text(encoding="utf-8")
    assert "install_scripts=$base/lib/core" in setup_cfg
    # the script itself is generated from this entry point; a rename would leave a unit
    # pointing at a file nobody builds any more
    setup_py = (ROOT / "src" / "runtime" / "gateway" / "setup.py").read_text(encoding="utf-8")
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


# --- D-189: every unit's sandbox covers what its program writes ------------
#
# Release 2026.09.23-005 booted with three sandbox defects no host test could
# see: the recovery gate could not write its journal (ProtectSystem=strict with
# no writable path), CORE's HOME was under ProtectHome=true, and CORE's
# StateDirectory=rosy chowned root-only state to rosy-core. These tests read the
# unit files as systemd would and compare them with what the programs write.

UNITS = sorted(path.name for path in NATIVE.glob("*.service"))
STATE_RULES = NATIVE / "tmpfiles-rosy-state.conf"

# Directories under /var/lib/rosy that only root may write (identity, the
# release journal, applied boot settings). No non-root unit may reach them.
ROOT_ONLY_STATE = (
    "/var/lib/rosy/provisioning",
    "/var/lib/rosy/releases",
    "/var/lib/rosy/config",
)

# What each ProtectSystem=strict unit's program writes, derived from the code.
# "$HOME" is the unit's Environment=HOME. Keep this next to the code references.
DECLARED_WRITES = {
    "rosy-release-recover.service": {
        # native_release.py NativeReleaseManager: self.lock is opened on every
        # recover, even without a journal; self.journal is rewritten/unlinked.
        "/var/lib/rosy/releases/native-release.lock",
        "/var/lib/rosy/releases/native-activation.json",
        # SymlinkStore.set: temporary ".<name>.new" link, then os.replace.
        "/opt/rosy/current", "/opt/rosy/previous", "/opt/rosy/.current.new",
    },
    "rosy-sd-provision.service": set(),
    "rosy-core.service": {
        # core_common/config.py LOCAL_CONFIG_PATH / overlay_path (API writes).
        "$HOME/.rosy/rosy.yaml",
        # core/node.py waypoints_path; services.py puts the rest beside it.
        "$HOME/.rosy/waypoints.json", "$HOME/.rosy/audit.jsonl",
        "$HOME/.rosy/docks.json", "$HOME/.rosy/battery-shutdown-request.json",
        # ROS logs (D-174 F6) and the host agent socket directory.
        "/var/log/rosy-core/core.log", "/run/rosy/host-agent.sock",
        # D-193: CORE's used/burned signal to rosy-login-code (api/v1/auth.py STATE_FILE).
        "/run/rosy/login-code-state.json",
        # D-247: CORE's refresh request to rosy-hw-probe.path (api/v1/host.py HW_REQUEST_FILE).
        "/run/rosy/hw-probe.request",
    },
    "rosy-io.service": {"/var/log/rosy-io/launch.log"},
    "rosy-navigation.service": {
        "/var/log/rosy-navigation/launch.log",
        # slam_toolbox save_map output: ros_bridge.py ROSY_MAP_OUTPUT_DIR default.
        "/var/lib/rosy/maps/site.pgm",
    },
    "rosy-boot-display.service": {
        # lgpio (under rpi-lgpio's RPi.GPIO) keeps its notification files in
        # LG_WD, which the unit points at HOME. The program itself writes nothing.
        "$HOME/.lgd-nfy0",
    },
    "rosy-login-code.service": {
        # rosy-login-code.py CODE_FILE, DISPLAY_FILE, ISSUE_FILE, LOCK_FILE, BOOT_MARK (D-193).
        "/run/rosy-boot/login-code.json", "/run/rosy-boot/login-display.txt",
        "/run/rosy-boot/login.issue", "/run/rosy-boot/.login.lock",
        "/run/rosy-boot/.login-boot-issued",
        # `agetty --reload` opens it for writing (ExecStartPre=+ creates it first).
        "/run/agetty.reload",
    },
    "rosy-hw-probe.service": {
        # rosy-hw-probe.py OUTPUT, via a temporary file beside it (D-247).
        "/run/rosy-boot/hardware.json",
    },
}

# Absolute paths a unit's program names but only reads.
DECLARED_READS = {
    "rosy-release-recover.service": {"/opt/rosy/releases"},  # verify() of old_current
    "rosy-core.service": {
        "/var/lib/rosy",       # calibration data_root, runtime probe default
        "/var/lib/rosy/maps",  # save_map read-back; slam_toolbox is the writer
        # D-193: the root issuer's verifier, root:rosy-core 0640. CORE never writes there (D-161).
        "/run/rosy-boot/login-code.json",
        # D-247: the root probe's result, root:rosy-core 0640 (api/v1/host.py HARDWARE_FILE).
        "/run/rosy-boot/hardware.json",
    },
    "rosy-navigation.service": {
        "/var/lib/rosy/maps/site.yaml", "/etc/rosy/line_follow.yaml", "/etc/rosy/profile.yaml",
    },
    # boot-status.json, network.json and ap-display.txt (root-written; D-190).
    "rosy-boot-display.service": {"/run/rosy-boot"},
    # D-193: boot-status.json; CORE's used/burned signal (read strictly, never
    # followed); the image defaults and the applied rosy-config policy.
    "rosy-login-code.service": {
        "/run/rosy-boot/boot-status.json", "/run/rosy/login-code-state.json",
        "/etc/rosy/defaults.yaml", "/etc/rosy/login-policy.json",
    },
    # D-247: the boot id, the CSI node status, the kernel log and the buzzer
    # settings of the boot display. Devices are opened, never written to disk.
    "rosy-hw-probe.service": {
        "/proc/sys/kernel/random/boot_id", "/proc/device-tree", "/dev/kmsg",
        "/etc/rosy/boot-display.env",
    },
}

# Program sources scanned for write roots, per unit.
PROGRAM_SOURCES = {
    "rosy-release-recover.service": ["deploy/robot/native/native_release.py",
                                     "deploy/robot/native/recover-release.sh"],
    "rosy-sd-provision.service": [],
    # CORE also imports modules of the control package (sensor adapter, gate).
    # control sits under src/core since a93d5188 but runs its nodes as their own
    # processes, so only the modules CORE imports count (PROGRAM_EXCLUDES).
    "rosy-core.service": [
        "src/runtime/gateway",
        "src/runtime/events",
        "src/runtime/services",
        "src/runtime/api_web",
        "src/contracts/foundation",
        "imported-by:src/runtime/gateway:control:src/runtime/sensing",
    ],
    "rosy-io.service": ["src/devices/pinky_pro/bringup"],
    "rosy-navigation.service": ["src/runtime/navigation", "src/devices/pinky_pro/bringup"],
    # D-190: the display loop, the emotion card and LCD driver, rosylib.Battery.
    "rosy-boot-display.service": ["deploy/robot/native/rosy-boot-display.py",
                                  "src/hmi/face/emotion/info_screen.py",
                                  "src/hmi/face/emotion/rosy_lcd.py",
                                  "src/devices/pinky_pro/bringup/rosylib"],
    # D-193: the issuer and the policy loader it imports.
    "rosy-login-code.service": ["deploy/robot/native/rosy-login-code.py",
                                "deploy/robot/native/rosy_config.py"],
    # D-247: the probe is standard library only (dynamixel_sdk is imported lazily).
    "rosy-hw-probe.service": ["deploy/robot/native/rosy-hw-probe.py"],
}

PATH_LITERAL = re.compile(r"""["'](/(?:var|opt|run|etc|srv|home|root)/[^"'\s]*)["']""")
SEGMENT_CHAIN = re.compile(r"""["'](var|opt|run|etc)["'](?:\s*/\s*["'][^"'/]+["'])+""")
HOME_USE = re.compile(r"Path\.home\(\)|expanduser\(|os\.path\.expanduser|[\"']~/")


def _directives(name: str) -> dict[str, list[str]]:
    """Directive values in file order; an empty assignment resets the list."""
    values: dict[str, list[str]] = {}
    for raw in _read(name).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value == "":
            values[key] = []
        else:
            values.setdefault(key, []).append(value)
    return values


def _words(directives: dict[str, list[str]], key: str) -> list[str]:
    return [word for value in directives.get(key, []) for word in value.split()]


def _environment(directives: dict[str, list[str]]) -> dict[str, str]:
    return dict(word.split("=", 1) for word in _words(directives, "Environment") if "=" in word)


def _managed(directives: dict[str, list[str]]) -> set[str]:
    """Directories systemd itself creates, chowns to User= and makes writable."""
    paths = {f"/var/lib/{entry}" for entry in _words(directives, "StateDirectory")}
    paths |= {f"/var/log/{entry}" for entry in _words(directives, "LogsDirectory")}
    paths |= {f"/run/{entry}" for entry in _words(directives, "RuntimeDirectory")}
    paths |= {f"/var/cache/{entry}" for entry in _words(directives, "CacheDirectory")}
    return paths


def _writable(directives: dict[str, list[str]]) -> list[tuple[str, bool]]:
    """(path, optional) for every path systemd makes writable for the unit."""
    paths = [(path, False) for path in sorted(_managed(directives))]
    for entry in _words(directives, "ReadWritePaths"):
        optional = entry.startswith("-")
        paths.append((entry.lstrip("-+"), optional))
    if directives.get("PrivateTmp") == ["true"]:
        paths += [("/tmp", False), ("/var/tmp", False)]
    return paths


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _expand(path: str, directives: dict[str, list[str]]) -> str:
    home = _environment(directives).get("HOME", "$HOME")
    return path.replace("$HOME", home)


IMPORT_OF = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.MULTILINE)


def _imported_modules(importer: str, package: str, package_root: str) -> list[Path]:
    """Files of `package` (rooted at package_root) that `importer` sources import."""
    found: set[Path] = set()
    own = ROOT / package_root
    for source in _source_files(importer):
        # The package's own imports are not the importer's: control sits inside
        # src/core since a93d5188, and would otherwise pull in all of itself.
        if source.is_relative_to(own):
            continue
        for name in IMPORT_OF.findall(source.read_text(encoding="utf-8", errors="replace")):
            parts = name.split(".")
            if parts[0] != package:
                continue
            for depth in range(len(parts), 0, -1):
                base = ROOT / package_root / Path(*parts[:depth])
                for candidate in (base.with_suffix(".py"), base / "__init__.py"):
                    if candidate.is_file():
                        found.add(candidate)
    return sorted(found)


# Trees inside a directory source that are not part of that unit's program.
PROGRAM_EXCLUDES = {
    "rosy-core.service": ("src/runtime/sensing",),
}


def _source_files(relative: str) -> list[Path]:
    if relative.startswith("imported-by:"):
        _tag, importer, package, package_root = relative.split(":")
        return _imported_modules(importer, package, package_root)
    root = ROOT / relative
    if root.is_file():
        return [root]
    return sorted(
        path for path in root.rglob("*")
        # Python only: shell files in a package tree are installers, not the program.
        if path.suffix == ".py" and "test" not in path.relative_to(root).parts
        and not {"build", "install", "log", "__pycache__"} & set(path.relative_to(root).parts)
    )


def _write_roots(unit: str) -> set[str]:
    """Absolute paths and HOME use the unit's program source names."""
    found: set[str] = set()
    excluded = [ROOT / item for item in PROGRAM_EXCLUDES.get(unit, ())]
    for relative in PROGRAM_SOURCES[unit]:
        for path in _source_files(relative):
            if not relative.startswith("imported-by:") and any(
                    path.is_relative_to(item) for item in excluded):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found.update(PATH_LITERAL.findall(text))
            for match in SEGMENT_CHAIN.finditer(text):
                found.add("/" + "/".join(re.findall(r"""["']([^"']+)["']""", match.group(0))))
            if HOME_USE.search(text):
                found.add("$HOME")
    return found


def test_every_native_unit_is_covered_by_the_sandbox_contract():
    # A new unit must declare what it writes before it can ship.
    strict = [name for name in UNITS if _directives(name).get("ProtectSystem") == ["strict"]]
    assert set(strict) == set(DECLARED_WRITES), sorted(set(strict) ^ set(DECLARED_WRITES))


@pytest.mark.parametrize("unit", UNITS)
def test_no_unit_takes_the_shared_rosy_state_parent(unit):
    directives = _directives(unit)
    assert "rosy" not in _words(directives, "StateDirectory"), unit
    for path, _optional in _writable(directives):
        assert path.rstrip("/") not in {"/var/lib", "/var/lib/rosy", "/opt", "/etc", "/etc/rosy"}, (unit, path)


def _non_root(directives: dict[str, list[str]]) -> bool:
    # No User= is root, which is systemd's default; DynamicUser= is not root.
    if directives.get("DynamicUser", ["no"])[-1] in {"yes", "true", "1", "on"}:
        return True
    return directives.get("User", ["root"])[-1] not in {"root", "0"}


@pytest.mark.parametrize("unit", UNITS)
def test_non_root_units_cannot_write_root_only_state(unit):
    directives = _directives(unit)
    if not _non_root(directives):
        return
    for path, _optional in _writable(directives):
        for protected in ROOT_ONLY_STATE:
            assert not _under(protected, path) and not _under(path, protected), (unit, path, protected)


@pytest.mark.parametrize("unit", sorted(DECLARED_WRITES))
def test_strict_units_can_write_everything_their_program_writes(unit):
    directives = _directives(unit)
    writable = [path for path, _optional in _writable(directives)]
    for declared in DECLARED_WRITES[unit]:
        target = _expand(declared, directives)
        assert "$HOME" not in target, f"{unit} writes {declared} but sets no HOME"
        assert any(_under(target, root) for root in writable), f"{unit}: {target} is read-only"


@pytest.mark.parametrize("unit", sorted(PROGRAM_SOURCES))
def test_declared_paths_account_for_every_write_root_in_the_program(unit):
    # Keeps DECLARED_WRITES honest: a new path literal or Path.home() in the
    # program fails here until someone classifies it as a write or a read.
    declared = DECLARED_WRITES[unit] | DECLARED_READS.get(unit, set())
    for root in _write_roots(unit):
        assert any(_under(item, root) or _under(root, item) for item in declared), (
            f"{unit}: program names {root}; declare it in DECLARED_WRITES or DECLARED_READS")


@pytest.mark.parametrize("unit", UNITS)
def test_protect_home_service_users_get_a_writable_home(unit):
    directives = _directives(unit)
    if directives.get("ProtectHome") != ["true"] or not _non_root(directives):
        return
    home = _environment(directives).get("HOME")
    assert home, f"{unit}: ProtectHome=true makes the passwd home unreadable; set HOME"
    assert any(_under(home, path) for path, _optional in _writable(directives)), (unit, home)


def test_the_core_program_really_uses_its_home():
    # The contract above only bites if CORE keeps using Path.home(); if that
    # changes, DECLARED_WRITES must move with it.
    assert "$HOME" in _write_roots("rosy-core.service")


@pytest.mark.parametrize("unit", UNITS)
def test_required_writable_paths_exist_when_the_unit_starts(unit):
    # A ReadWritePaths entry that does not exist fails the unit with
    # 226/NAMESPACE. It must be managed by this unit, created by tmpfiles or the
    # image, or come from a unit this one requires.
    directives = _directives(unit)
    created = set(_managed(directives))
    # tmpfiles runs in systemd-tmpfiles-setup.service; a DefaultDependencies=no
    # unit may start before it unless it orders itself after it.
    early = directives.get("DefaultDependencies") == ["no"]
    if not early or "systemd-tmpfiles-setup.service" in _words(directives, "After"):
        created |= {line.split()[1] for line in STATE_RULES.read_text(encoding="utf-8").splitlines()
                    if line.startswith("d ")}
    created.add("/opt/rosy")  # customize-rootfs.sh installs the release store there
    for required in _words(directives, "Requires"):
        if required.endswith(".service") and (NATIVE / required).is_file():
            created |= {f"/run/{entry}" for entry in _words(_directives(required), "RuntimeDirectory")}
    for entry in _words(directives, "ReadWritePaths"):
        if entry.startswith("-"):
            continue
        assert entry.lstrip("+") in created, f"{unit}: {entry} may not exist at start"


def test_state_rules_keep_the_parent_and_root_only_state_with_root():
    rules = STATE_RULES.read_text(encoding="utf-8")
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    customizer = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")

    assert "d /var/lib/rosy 0755 root root -" in rules
    assert "d /var/lib/rosy/maps 2750 rosy-io rosy-core -" in rules
    for protected in ROOT_ONLY_STATE:
        assert f"Z {protected} - root root -" in rules
    # A map left owned by rosy-core on a 005 card must not block slam_toolbox.
    assert "z /var/lib/rosy/maps/* - rosy-io rosy-core -" in rules
    assert 'tmpfiles-rosy-state.conf" "$OVERLAY/etc/tmpfiles.d/rosy-state.conf"' in payload
    assert 'install -d -m 0755 -o root -g root "$ROOT/var/lib/rosy"' in customizer
    assert "install -d -m 2750 -o rosy-io -g rosy-core /var/lib/rosy/maps" in customizer
    # The accounts must exist before the chroot install names them.
    assert customizer.index("useradd --uid 961") < customizer.index("-o rosy-io -g rosy-core")


def test_contract_parser_sees_the_2026_09_23_005_defects():
    # The guard must fail on the units that shipped, not only pass on the fixed ones.
    shipped_core = {
        "User": ["rosy-core"], "ProtectSystem": ["strict"], "ProtectHome": ["true"],
        "StateDirectory": ["rosy"], "ReadWritePaths": ["/var/lib/rosy /run/rosy"],
        "LogsDirectory": ["rosy-core"],
    }
    writable = [path for path, _optional in _writable(shipped_core)]
    assert "/var/lib/rosy" in writable
    assert any(_under("/var/lib/rosy/provisioning", path) for path in writable)
    assert "HOME" not in _environment(shipped_core)

    shipped_recover = {"ProtectSystem": ["strict"], "ProtectHome": ["true"]}
    writable = [path for path, _optional in _writable(shipped_recover)]
    assert not any(_under("/var/lib/rosy/releases/native-release.lock", path) for path in writable)


# --- D-189 review: a writable HOME must not become a startup hook ----------

HOME_UNITS = ("rosy-core.service", "rosy-io.service", "rosy-navigation.service")


@pytest.mark.parametrize("unit", UNITS)
def test_units_with_a_writable_home_run_nothing_from_it(unit):
    # bash -l sources ~/.profile and ~/.bash_profile; Python adds ~/.local and
    # imports usercustomize. With HOME writable by the service, a compromised
    # process could plant code that runs before the signed release on every
    # start and survives OTA.
    directives = _directives(unit)
    home = _environment(directives).get("HOME")
    if not home or not any(_under(home, path) for path, _optional in _writable(directives)):
        return
    assert _environment(directives).get("PYTHONNOUSERSITE") == "1", unit
    for key in ("ExecStartPre", "ExecStart", "ExecStartPost", "ExecReload", "ExecStop", "ExecStopPost"):
        for command in directives.get(key, []):
            words = command.split()
            shell = words[0].lstrip("-+!@:").rsplit("/", 1)[-1] if words else ""
            if shell in {"bash", "sh", "dash"}:
                assert "--noprofile" in words and "--norc" in words, (unit, key, command)
                flags = [word for word in words[1:] if word.startswith("-") and not word.startswith("--")]
                assert not any("l" in flag for flag in flags), (unit, key, command)
                assert "--login" not in words, (unit, key, command)


def test_every_home_unit_is_covered_by_the_startup_hook_rule():
    for unit in HOME_UNITS:
        directives = _directives(unit)
        assert _environment(directives).get("HOME"), unit
        assert _environment(directives).get("PYTHONNOUSERSITE") == "1", unit
        assert "/usr/bin/bash --noprofile --norc -c '" in _read(unit), unit
        assert "bash -lc" not in _read(unit), unit


@pytest.mark.parametrize("unit", [
    "rosy-core.service", "rosy-io.service", "rosy-navigation.service", "rosy-boot-display.service",
])
def test_python_units_never_write_bytecode_into_the_release(unit):
    # D-225: the payload ships checked-hash pycs (valid after pack fixes mtimes);
    # the runtime must not add or rewrite any under the signed release.
    assert _environment(_directives(unit)).get("PYTHONDONTWRITEBYTECODE") == "1", unit


def test_payload_build_rewrites_pycs_as_checked_hash():
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    compile_at = payload.index("python3 -m compileall -q -f --invalidation-mode checked-hash")
    assert payload.index("colcon build") < compile_at < payload.index('"$INSTALL_ROOT/.rosy-release"')


def test_the_login_code_issuer_is_a_root_sandbox_without_network():
    # D-193 2: root outside CORE, no network, only /run/rosy-boot writable.
    directives = _directives("rosy-login-code.service")
    assert not _non_root(directives)
    for key, value in (("PrivateNetwork", "true"), ("RestrictAddressFamilies", "AF_UNIX"),
                       ("ProtectSystem", "strict"), ("ProtectHome", "true"),
                       ("NoNewPrivileges", "true"), ("Restart", "always")):
        assert directives.get(key, [""])[-1] == value, key
    assert _words(directives, "ReadWritePaths") == ["/run/rosy-boot", "-/run/agetty.reload"]
    assert _environment(directives).get("PYTHONNOUSERSITE") == "1"
    assert "rosy-boot-status.service" in _words(directives, "After")
    assert directives["ExecStart"] == [
        "/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-login-code.py --daemon"]
    assert directives["ExecStartPre"] == ["+/usr/bin/touch /run/agetty.reload"]
    assert "bash" not in _read("rosy-login-code.service")
    # It never writes where CORE runs (/run/rosy is rosy-core's).
    assert not any(_under(path, "/run/rosy") for path, _optional in _writable(directives))


def test_the_hardware_probe_is_a_bounded_root_oneshot_without_network():
    # D-247 4: root outside CORE, run once after boot and on CORE's request;
    # only /run/rosy-boot writable, never /run/rosy (CORE's; D-161).
    directives = _directives("rosy-hw-probe.service")
    assert not _non_root(directives)
    for key, value in (("Type", "oneshot"), ("PrivateNetwork", "true"), ("RestrictAddressFamilies", "AF_UNIX"),
                       ("ProtectSystem", "strict"), ("ProtectHome", "true"), ("NoNewPrivileges", "true"),
                       ("DevicePolicy", "closed"), ("StartLimitIntervalSec", "0")):
        assert directives.get(key, [""])[-1] == value, key
    timeout = int(directives["TimeoutStartSec"][-1])
    assert 0 < timeout <= 120
    assert _words(directives, "ReadWritePaths") == ["/run/rosy-boot"]
    assert not any(_under(path, "/run/rosy") for path, _optional in _writable(directives))
    assert _environment(directives).get("PYTHONNOUSERSITE") == "1"
    assert "rosy-core.service" in _words(directives, "After")
    assert directives["ExecStart"] == ["/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-hw-probe.py"]
    assert "Restart" not in directives
    assert "bash" not in _read("rosy-hw-probe.service")

    path = _read("rosy-hw-probe.path")
    assert "PathChanged=/run/rosy/hw-probe.request" in path
    assert "Unit=rosy-hw-probe.service" in path
    assert "WantedBy=multi-user.target" in path
    # CORE writes the request file in its own RuntimeDirectory.
    assert "RuntimeDirectory=rosy" in _read("rosy-core.service")


def test_recovery_journal_is_private_to_root():
    directives = _directives("rosy-release-recover.service")
    assert directives.get("StateDirectoryMode") == ["0700"]
    assert "User" not in directives


def test_contract_helpers_treat_dynamic_users_as_non_root():
    assert _non_root({"DynamicUser": ["yes"]})
    assert _non_root({"User": ["rosy-io"]})
    assert not _non_root({})
    assert not _non_root({"User": ["root"]})


def test_core_program_scan_follows_imports_into_the_control_package():
    # CORE's production modules import no control module today (only its tests
    # do), so the scan adds nothing now; it picks them up the moment one does.
    assert "imported-by:src/runtime/gateway:control:src/runtime/sensing" in PROGRAM_SOURCES["rosy-core.service"]
    resolved = {path.relative_to(ROOT).as_posix()
                for path in _imported_modules("src/runtime/gateway/test", "control", "src/runtime/sensing")}
    assert "src/runtime/sensing/control/sensor_provider.py" in resolved
    assert "src/runtime/sensing/control/calibration_storage.py" in resolved
