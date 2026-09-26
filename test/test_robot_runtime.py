"""Static contract tests for the Raspberry Pi robot runtime."""

import sys

import yaml

from robot_contracts import (
    DEPLOY,
    ROOT,
    board_caps,
    board_profile,
    compose,
    runtime_launch_closure,
)

sys.path.insert(0, str(ROOT / "src" / "runtime" / "navigation"))
from navigation.profile_limits import load_motion_limits


def _hardware_motion_tokens() -> tuple[str, str]:
    limits = load_motion_limits(DEPLOY / "config" / "profile.hardware.yaml")
    return f"{limits.max_linear_mps:.2f}", f"{limits.max_angular_rps:.2f}"


def test_runtime_separates_core_from_hardware_devices():
    services = compose()["services"]

    assert set(services) == {"rosy-core", "rosy-motor", "rosy-io"}
    assert "devices" not in services["rosy-core"]
    assert services["rosy-core"].get("privileged", False) is False
    assert services["rosy-motor"].get("privileged", False) is False
    assert services["rosy-io"].get("privileged", False) is False
    assert services["rosy-motor"]["devices"] == [
        "${ROSY_MOTOR_DEVICE:-/dev/ttyAMA4}:/dev/rosy-motor",
    ]
    assert services["rosy-io"]["devices"] == [
        "${ROSY_MOTOR_DEVICE:-/dev/ttyAMA4}:/dev/rosy-motor",
        "${ROSY_LIDAR_DEVICE:-/dev/ttyAMA0}:/dev/ttyAMA0",
        "${ROSY_CAMERA_DEVICE:-/dev/video0}:/dev/video0",
        "${ROSY_I2C_DEVICE:-/dev/i2c-1}:/dev/i2c-1",
    ]


def test_runtime_uses_local_ros_network_and_bounded_logs():
    services = compose()["services"]

    for service in services.values():
        assert service["network_mode"] == "host"
        assert service["restart"] == "unless-stopped"
        assert service["logging"]["driver"] == "local"
        assert service["logging"]["options"] == {
            "max-size": "10m",
            "max-file": "3",
        }
        # 기본값이 있으면 모든 기기가 같은 도메인으로 뜬다 — 없는 것이 계약이다 (ADR D-33).
        domain = service["environment"]["ROS_DOMAIN_ID"]
        assert domain.startswith("${ROS_DOMAIN_ID:?"), domain
        assert ":-" not in domain, domain


def test_runtime_uses_one_namespace_and_a_real_core_health_endpoint():
    services = compose()["services"]
    namespace_arg = "__ns:=/${ROSY_NAMESPACE}"
    # 네임스페이스도 마찬가지다 — :51 이 실제로 기동에 쓰이는 인자이므로,
    # :8 만 고치고 여기를 두면 반쪽 수정이 된다. 신원 키에 한해서만 본다.
    compose_text = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    for key in ("ROS_DOMAIN_ID", "ROSY_NAMESPACE"):
        assert f"${{{key}:-" not in compose_text, (
            f"compose.yaml still defaults {key}"
        )

    assert namespace_arg in services["rosy-core"]["command"]
    assert "namespace:=${ROSY_NAMESPACE}" in services["rosy-motor"]["command"]
    assert "namespace:=${ROSY_NAMESPACE}" in services["rosy-io"]["command"]
    assert "/api/v1" in " ".join(services["rosy-core"]["healthcheck"]["test"])
    number = services["rosy-core"]["environment"]["ROSY_ROBOT_NUMBER"]
    assert number == "${ROSY_ROBOT_NUMBER:-}", number
    assert "${ROSY_ROBOT_NUMBER:?" not in (DEPLOY / "compose.yaml").read_text(encoding="utf-8")


def test_runtime_builds_distinct_targets_from_shared_dockerfile():
    services = compose()["services"]
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

    assert services["rosy-core"]["build"]["target"] == "core"
    assert services["rosy-motor"]["build"]["target"] == "io"
    assert services["rosy-io"]["build"]["target"] == "io"
    assert "AS core" in dockerfile
    assert "AS io" in dockerfile
    assert "ros:jazzy-ros-base" in dockerfile
    assert "ros-jazzy-rmw-cyclonedds-cpp" in dockerfile
    assert "ros-jazzy-joint-state-publisher" in dockerfile
    assert "SLLIDAR_COMMIT=34300099fadfc772965962dec837bf436706188f" in dockerfile
    assert "git checkout --detach ${SLLIDAR_COMMIT}" in dockerfile
    assert "COPY --from=core-build /opt/rosy_ws/install" in dockerfile
    assert "COPY --from=io-build /opt/rosy_ws/install" in dockerfile
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "src/sim/description/meshes/**" in dockerignore
    # D-196: the core stage copies the robot package CORE reads its profile from.
    assert "COPY src/products/pinky_pro ./src/products/pinky_pro" in dockerfile
    for allowed in ("!src/products/", "!src/products/pinky_pro/", "!src/products/pinky_pro/**"):
        assert allowed in dockerignore.splitlines(), allowed


def test_dockerignore_admits_every_source_path_the_dockerfile_copies():
    # .dockerignore excludes everything and re-admits a whitelist. After a
    # tree move the whitelist kept src/apps and src/hardware while COPY moved
    # on, so the io build failed at COPY. Every COPY source must be admitted.
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    admitted = set((ROOT / ".dockerignore").read_text(encoding="utf-8").split())
    sources = {
        line.split()[1]
        for line in dockerfile.splitlines()
        if line.startswith("COPY src/")
    }

    assert sources
    missing = [
        source for source in sorted(sources)
        if not any(f"!{parent}/**" in admitted or f"!{parent}" in admitted
                   for parent in _self_and_parents(source))
    ]
    assert missing == []


def _self_and_parents(path: str) -> list[str]:
    parts = path.rstrip("/").split("/")
    return ["/".join(parts[:end]) for end in range(len(parts), 0, -1)]


def test_motion_profile_is_mounted_into_each_device_runtime():
    services = compose()["services"]
    profile_mount = "./config/profile.${ROSY_RUNTIME_MODE:-core}.yaml:/etc/rosy/profile.yaml:ro"
    motion_mount = "./config/motion_profiles.yaml:/etc/rosy/motion_profiles.yaml:ro"

    assert profile_mount in services["rosy-motor"]["volumes"]
    assert profile_mount in services["rosy-io"]["volumes"]
    assert motion_mount in services["rosy-core"]["volumes"]
    assert motion_mount in services["rosy-motor"]["volumes"]
    assert motion_mount in services["rosy-io"]["volumes"]
    assert services["rosy-io"]["environment"]["ROSY_MOTION_PROFILE_FILE"] == (
        "/etc/rosy/motion_profiles.yaml"
    )


def test_core_image_does_not_ship_the_absorbed_sensor_worker_runtime():
    """CORE boots without control; the adapter is an optional slice."""
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    core = dockerfile.split("FROM runtime-common AS io-runtime")[0]

    assert "COPY src/runtime/sensing ./src/runtime/sensing" not in core
    assert "python3-opencv" not in core
    assert "ros-jazzy-visualization-msgs" in core
    assert "ros-jazzy-tf2-ros" in core
    assert "python3-numpy" in core
    assert "python3-yaml" in core


def test_io_image_contains_the_disabled_omx_adapter_contract():
    """The Device image ships the model-neutral OMX boundary without enabling hardware."""
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY src/devices/omx/adapter ./src/devices/omx/adapter" in dockerfile
    assert "omx_adapter" in dockerfile
    disabled = (
        ROOT / "src" / "products" / "omx" / "config" / "omx.disabled.yaml"
    ).read_text(encoding="utf-8")
    assert "enabled: false" in disabled
    assert "hardware_plugin: \"\"" in disabled


def test_initial_io_slice_disables_unavailable_adc_battery_driver():
    compose_command = compose()["services"]["rosy-io"]["command"]
    launch = (
        ROOT / "src" / "devices" / "pinky_pro" / "bringup" / "launch" / "bringup_robot.launch.py"
    ).read_text(encoding="utf-8")

    assert "enable_battery:=false" in compose_command
    assert "DeclareLaunchArgument('enable_battery', default_value='false'" in launch
    assert "condition=IfCondition(enable_battery)" in launch
    assert "on_exit=Shutdown(" in launch


def test_motor_only_profile_excludes_lidar_and_passes_uart_parameters():
    services = compose()["services"]
    motor = services["rosy-motor"]
    command = motor["command"]

    assert motor["profiles"] == ["motor"]
    assert "enable_lidar:=false" in command
    assert "motor_device:=/dev/rosy-motor" in command
    assert "motor_baudrate:=${ROSY_MOTOR_BAUDRATE:-1000000}" in command
    assert "motor_ids:=${ROSY_MOTOR_IDS:-[1,2]}" in command
    linear, angular = _hardware_motion_tokens()
    assert f"max_linear_mps:=${{ROSY_MAX_LINEAR_MPS:-{linear}}}" in command
    assert f"max_angular_rps:=${{ROSY_MAX_ANGULAR_RPS:-{angular}}}" in command
    assert "max_wheel_rpm:=${ROSY_MAX_WHEEL_RPM:-100.0}" in command
    assert (
        "motor_profile_acceleration:=${ROSY_MOTOR_PROFILE_ACCELERATION:-200}"
        in command
    )
    assert all("ttyAMA0" not in device for device in motor["devices"])


def test_hardware_profile_passes_the_same_motor_safety_limits():
    command = compose()["services"]["rosy-io"]["command"]
    linear, angular = _hardware_motion_tokens()

    assert f"max_linear_mps:=${{ROSY_MAX_LINEAR_MPS:-{linear}}}" in command
    assert f"max_angular_rps:=${{ROSY_MAX_ANGULAR_RPS:-{angular}}}" in command
    assert "max_wheel_rpm:=${ROSY_MAX_WHEEL_RPM:-100.0}" in command
    assert (
        "motor_profile_acceleration:=${ROSY_MOTOR_PROFILE_ACCELERATION:-200}"
        in command
    )


def test_example_environment_exposes_motor_limits_as_data_only_values():
    environment = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    linear, angular = _hardware_motion_tokens()

    assert f"ROSY_MAX_LINEAR_MPS={linear}" in environment
    assert f"ROSY_MAX_ANGULAR_RPS={angular}" in environment
    assert "ROSY_MAX_WHEEL_RPM=100.0" in environment
    assert "ROSY_MOTOR_PROFILE_ACCELERATION=200" in environment
    assert "ROSY_MAP=/var/lib/rosy/maps/site.yaml" in environment


def test_io_health_requires_the_motor_node_to_be_discoverable():
    io = compose()["services"]["rosy-io"]

    assert "healthcheck" in io
    assert "/${ROSY_NAMESPACE}/bringup" in " ".join(
        io["healthcheck"]["test"]
    )


def test_core_data_is_a_host_owned_bind_and_capabilities_match_the_slice():
    runtime = compose()
    core = runtime["services"]["rosy-core"]

    assert "${ROSY_DATA_PATH:-/var/lib/rosy}:/var/lib/rosy" in core["volumes"]
    assert "volumes" not in runtime
    assert (
        "./config/profile.${ROSY_RUNTIME_MODE:-core}.yaml:/etc/rosy/profile.yaml:ro"
        in core["volumes"]
    )
    assert (
        "./config/${ROSY_CAPABILITIES_FILE:-capabilities.core.yaml}"
        ":/etc/rosy/capabilities.yaml:ro"
        in core["volumes"]
    )


def test_core_mode_does_not_advertise_motion_hardware():
    caps = board_caps("core")
    profile = board_profile("core")

    assert caps["teleop"] is False
    assert caps["sensors"] == []
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["slam"] is False
    assert caps["swarm"] == {"follow": False, "lead": False}
    assert profile["profile"]["sensors"] == []


def test_motor_mode_advertises_teleop_without_lidar():
    caps = board_caps("motor")
    profile = board_profile("motor")

    assert caps["teleop"] is True
    assert caps["sensors"] == ["encoder"]
    assert "lidar" not in caps["sensors"]
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["swarm"] == {"follow": False, "lead": False}
    assert profile["profile"]["sensors"] == [{"encoder": "dynamixel"}]


def test_pi5_lite_is_a_board_alias_not_a_copied_overlay():
    catalog = yaml.safe_load((DEPLOY / "config" / "board.yaml").read_text(encoding="utf-8"))
    resolve = (DEPLOY / "config" / "resolve-mode.sh").read_text(encoding="utf-8")
    wrapper = (DEPLOY / "runtime-mode.sh").read_text(encoding="utf-8")

    assert catalog["aliases"]["pi5-lite"] == "hardware"
    assert "resolve_runtime_mode" in resolve
    assert "resolve-mode.sh" in wrapper
    assert not (DEPLOY / "config" / "capabilities.pi5-lite.yaml").is_file()
    assert not (DEPLOY / "config" / "profile.pi5-lite.yaml").is_file()


def test_board_catalog_lists_every_runtime_overlay():
    catalog = yaml.safe_load((DEPLOY / "config" / "board.yaml").read_text(encoding="utf-8"))
    assert catalog["board"] == "pinky_pro"
    assert set(catalog["modes"]) == {"core", "motor", "hardware"}
    for mode, spec in catalog["modes"].items():
        assert spec["capabilities"] == f"capabilities.{mode}.yaml"
        assert spec["profile"] == f"profile.{mode}.yaml"
        assert (DEPLOY / "config" / spec["capabilities"]).is_file()
        assert (DEPLOY / "config" / spec["profile"]).is_file()
        caps = board_caps(mode)
        assert caps["teleop"] is spec["teleop"]
        assert caps["sensors"] == spec["sensors"]
    assert catalog["aliases"]["pi5-lite"] == "hardware"


def test_core_container_receives_runtime_mode():
    env = compose()["services"]["rosy-core"]["environment"]
    assert env["ROSY_RUNTIME_MODE"] == "${ROSY_RUNTIME_MODE:-core}"
    assert env["ROSY_DATA_PATH"] == "/var/lib/rosy"


def test_runtime_mode_wrapper_requires_overlay_files():
    script = (DEPLOY / "runtime-mode.sh").read_text(encoding="utf-8")
    assert "resolve-mode.sh" in script
    assert "capabilities.${MODE}.yaml" in script
    assert "profile.${MODE}.yaml" in script
    assert "missing board overlay" in script


def test_core_reads_only_bounded_host_telemetry_paths():
    core = compose()["services"]["rosy-core"]
    mounts = set(core["volumes"])

    assert core["environment"]["ROSY_HOST_ROOT"] == "${ROSY_HOST_ROOT:-/host}"
    assert {
        "/proc/uptime:/host/proc/uptime:ro",
        "/proc/loadavg:/host/proc/loadavg:ro",
        "/proc/stat:/host/proc/stat:ro",
        "/proc/net/dev:/host/proc/net/dev:ro",
        "/proc/meminfo:/host/proc/meminfo:ro",
        "/sys/class/thermal:/host/sys/class/thermal:ro",
        "/sys/devices/virtual/thermal:/host/sys/devices/virtual/thermal:ro",
        "/etc/os-release:/host/etc/os-release:ro",
        "/etc/hostname:/host/etc/hostname:ro",
    } <= mounts
    assert "/:/host:ro" not in mounts
    assert "/var/run/docker.sock:/var/run/docker.sock" not in mounts


def test_core_image_prepares_dashboard_and_host_mount_directories():
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    setup = (ROOT / "src" / "runtime" / "gateway" / "setup.py").read_text(encoding="utf-8")

    assert (
        "mkdir -p /host/proc/net /host/etc /host/sys/class/thermal "
        "/host/sys/devices/virtual/thermal"
    ) in dockerfile
    assert "web/*.html" in setup
    assert "web/*.css" in setup
    assert "web/*.js" in setup


def test_systemd_unit_delegates_to_runtime_mode_wrapper():
    unit = (DEPLOY / "rosy-runtime.service").read_text(encoding="utf-8")

    assert "Requires=docker.service" in unit
    assert "EnvironmentFile=-/opt/rosy/deploy/robot/.env" in unit
    assert "runtime-mode.sh up" in unit
    assert "runtime-mode.sh down" in unit
    assert "docker compose" not in unit


def test_teleop_watchdog_lives_in_safety_manager_not_a_stub():
    safety = ROOT / "src" / "runtime" / "services" / "core_features" / "safety"
    assert not (safety / "watchdog.py").is_file()
    assert "class TeleopWatchdog" in (safety / "manager.py").read_text(encoding="utf-8")


def test_container_entrypoint_is_forced_to_unix_line_endings():
    entrypoint = (DEPLOY / "entrypoint.sh").read_bytes()
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert b"\r\n" not in entrypoint
    assert "*.sh text eol=lf" in attributes


# --- 저배터리 셧다운 (D-27) ---------------------------------------------------
#
# CORE 는 uid 1000 비특권이라 호스트를 끌 수 없다. 파일로 관찰을 남기고 호스트
# 유닛이 판단·실행한다. 명령 채널이 아니므로 소켓도 인증도 없다.
# 설계: docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md

def _unit(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def _directives(text: str) -> dict:
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, value = line.split("=", 1)
            found.setdefault(key.strip(), []).append(value.strip())
    return found


def test_lowbatt_path_unit_watches_the_sentinel_core_writes():
    directives = _directives(_unit("rosy-lowbatt-shutdown.path"))

    watched = directives["PathExists"]
    assert len(watched) == 1
    assert watched[0].endswith("/battery-shutdown-request.json")
    # CORE 의 데이터 디렉터리 — compose 의 ROSY_DATA_PATH 바인드와 같은 곳이어야 한다.
    assert watched[0].startswith("/var/lib/rosy")
    assert directives["WantedBy"] == ["multi-user.target"]


def test_lowbatt_service_is_a_oneshot_that_checks_before_it_halts():
    text = _unit("rosy-lowbatt-shutdown.service")
    directives = _directives(text)

    assert directives["Type"] == ["oneshot"]
    # 판단은 호스트가 한다 — 파일을 보자마자 끄지 않는다.
    assert any("rosy-lowbatt-shutdown.sh" in value
               for value in directives["ExecStart"])


def test_lowbatt_service_never_runs_at_boot_on_its_own():
    """/var/lib/rosy 는 영속이다. path 유닛만이 이 서비스를 띄워야 한다."""
    directives = _directives(_unit("rosy-lowbatt-shutdown.service"))
    assert "WantedBy" not in directives
    assert "RequiredBy" not in directives


def test_lowbatt_guard_refuses_a_stale_sentinel():
    """불결한 종료로 살아남은 파일이 다음 부팅을 끄면 안 된다."""
    script = (DEPLOY / "rosy-lowbatt-shutdown.sh").read_text(encoding="utf-8")
    assert "ROSY_LOWBATT_MAX_AGE_S" in script
    assert "requested_at" in script
    assert "systemctl" in script or "halt" in script


def test_lowbatt_guard_rechecks_the_file_after_the_grace_period():
    """유예 중 충전이 시작되면 CORE 가 파일을 지운다 — 그때 꺼지면 안 된다."""
    script = (DEPLOY / "rosy-lowbatt-shutdown.sh").read_text(encoding="utf-8")
    assert "grace_seconds" in script
    assert "sleep" in script


def test_installer_enables_the_lowbatt_units_alongside_the_runtime():
    installer = (DEPLOY / "install-pi.sh").read_text(encoding="utf-8")
    assert "rosy-lowbatt-shutdown.path" in installer
    assert "rosy-lowbatt-shutdown.service" in installer
    assert "rosy-lowbatt-shutdown.sh" in installer
    # 기존 런타임 유닛 처리는 그대로여야 한다.
    assert "systemctl enable --now rosy-runtime.service" in installer


def test_slam_capability_requires_a_launch_that_actually_starts_slam_toolbox():
    """Maintainability rule 5, enforced instead of remembered.

    An overlay may advertise `slam` only if the runtime it describes can do it.
    This is also condition 1 of the `mapping/` package re-entry trigger in
    `docs/plans/2026-09-06-module-split-criteria.md`: today every overlay is
    `slam: false` and nothing deployed starts slam_toolbox, so a `mapping/`
    package would have no runtime to be verified against. The day someone flips
    an overlay to true, this fails and points them at that decision instead of
    letting the advertisement drift ahead of the launch tree.

    Passes vacuously today. That is the intended state, not a gap.
    """
    for mode in ("core", "motor", "hardware"):
        if not board_caps(mode).get("slam", False):
            continue
        closure = runtime_launch_closure(mode)
        starts_slam = sorted(
            name for name, path in closure.items()
            if "slam_toolbox" in path.read_text(encoding="utf-8")
        )
        assert starts_slam, (
            f"capabilities.{mode}.yaml advertises slam: true, but no launch "
            f"reachable from compose starts slam_toolbox (reachable: "
            f"{sorted(closure)}). Either wire the launch or set slam: false.\n"
            "This also fires condition 1 of the mapping/ package re-entry "
            "trigger — see docs/plans/2026-09-06-module-split-criteria.md "
            "before adding a mapping/ package."
        )


def test_launch_closure_walks_the_deployed_launch_tree():
    """Keep the slam gate's own machinery exercised while the gate is quiet.

    The gate above only calls `runtime_launch_closure` when an overlay sets
    `slam: true`, and all three are false — correctly, and hopefully for a long
    time. That leaves the walker itself unrun: a typo in the reference regex or
    the resolver would stay green until the day someone flips an overlay, which
    is the worst moment to discover the gate never worked.

    Pinned here: the two launch-file naming conventions this tree actually uses
    (`hardware.launch.py` and `bringup_launch.xml` — a `*.launch.*` pattern
    alone silently halves the closure), transitive descent, and the per-profile
    scoping the gate depends on.
    """
    hardware = runtime_launch_closure("hardware")

    # Roots come from compose; the rest are only reachable transitively.
    assert "hardware.launch.py" in hardware
    assert "bringup_launch.xml" in hardware, "underscore-style includes must be followed"
    assert {"localization_launch.xml", "navigation_launch.xml"} <= set(hardware), (
        "bringup_launch.xml's own includes are two levels down from compose"
    )
    assert all(path.is_file() for path in hardware.values())

    # Profiles scope the roots: rosy-io is [hardware], rosy-motor is [motor],
    # and rosy-core launches nothing at all.
    assert runtime_launch_closure("core") == {}
    assert set(runtime_launch_closure("motor")) < set(hardware)
