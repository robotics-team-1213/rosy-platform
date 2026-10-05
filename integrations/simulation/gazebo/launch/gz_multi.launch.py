#!/usr/bin/env python3
"""gz_multi.launch.py — gz_sim 멀티 인스턴스 런치 (P0-6, ROSY-PLN-001).

N대의 로봇을 rosy_01 .. rosy_NN namespace로 시뮬레이션한다.

- Gazebo 서버(+옵션 GUI) 1회 기동
- 로봇별: namespaced robot_state_publisher (frame_prefix), spawn(create),
  per-robot ros_gz bridge (gz 토픽이 xacro namespace로 접두되므로
  `rosy_XX/cmd_vel` ↔ `rosy_XX/cmd_vel` 매핑을 런치 시점에 생성)
- 로봇별 Nav2(gz_bringup_launch.xml, A-5 패턴) 또는 SLAM 선택

알려진 제약(런타임 검증 M0 예정):
- SLAM 모드에서 mapper_params.yaml의 scan_topic 절대경로 여부 확인 필요
  (발견 사항 A-1과 동일 계열 — 로봇별 파라미터 오버라이드로 해결)

사용 예:
  ros2 launch gz_sim gz_multi.launch.py robots:=2
  ros2 launch gz_sim gz_multi.launch.py robots:=3 mode:=slam headless:=true
  ros2 launch gz_sim gz_multi.launch.py robots:=3 mode:=nav core:=true   # 로봇별 core, 8080..8082
"""

import math
import os
import sys
import tempfile

_LAUNCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _LAUNCH_DIR not in sys.path:
    sys.path.insert(0, _LAUNCH_DIR)
from gz_multi_args import (apply_nav_composition, apply_sim_speed, nav_composition_argument,
                           optional_float as _optional_float, sim_speed_arguments)
from gz_multi_parts import (SIM_OPERATOR_TOKEN, bridge_config as _bridge_config,
                            core_config as _core_config, load_run_spec as _load_run_spec,
                            robots_manifest as _robots_manifest,
                            run_spec_overlay as _run_spec_overlay)
from world_profiles import (parse_spawn_poses, resolve_asset_path, resolve_world, resolve_world_path,
                            spawn_xy, world_share_parent)

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
    SetEnvironmentVariable,
    TimerAction,
)
from launch_ros.actions import Node, PushRosNamespace, SetRemap
from launch.launch_description_sources import AnyLaunchDescriptionSource, PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

import yaml


def _slam_config(ns: str, rosy_nav_share: str) -> dict:
    """로봇별 slam_toolbox 파라미터.

    저장소의 mapper_params.yaml 은 단일 로봇용이다(`scan_topic: /scan`, 접두 없는
    프레임). 네임스페이스로 N대를 띄우면 스캔은 `/rosy_XX/scan` 으로 오고 TF 는
    robot_state_publisher 의 frame_prefix 때문에 `rosy_XX/` 가 붙으므로, 그대로 쓰면
    slam_toolbox 는 스캔도 TF 도 찾지 못한다. 기본값을 읽어 로봇별로만 덮어쓴다.

    `/**` 로 감싸는 이유: 노드가 `/rosy_XX/slam_toolbox` 라 파일의 최상위 키가
    `slam_toolbox` 이면 이름이 맞지 않아 파라미터가 하나도 적용되지 않는다.
    """
    defaults_path = os.path.join(rosy_nav_share, "params", "mapper_params.yaml")
    with open(defaults_path, encoding="utf-8") as f:
        defaults = yaml.safe_load(f)
    params = dict(defaults["slam_toolbox"]["ros__parameters"])
    params.update({
        "scan_topic": f"/{ns}/scan",
        "odom_frame": f"{ns}/odom",
        "base_frame": f"{ns}/base_footprint",
        # map 은 공유 루트 프레임으로 둔다(core 가 `map` 기준으로 목표를 낸다).
        # 로봇별 맵 내용은 SetRemap 으로 나눈 `/rosy_XX/map` 토픽이 구분한다.
        "map_frame": "map",
        "use_sim_time": True,
        # 기본값(0.5 m / 0.5 rad)은 실기 기준이다. 시뮬 월드는 4x3 m 남짓이고 pinky 는
        # 12 cm 라, 0.5 rad 마다 키프레임을 잡으면 제자리 회전 중 스캔 사이 각도차가
        # coarse_search_angle_offset(0.349 rad)를 넘겨 매칭이 어긋나고 맵에 회전 중복상이
        # 남는다. 로봇·월드 크기에 맞춰 키프레임을 촘촘히 잡는다.
        # Ten-millimetre track walls and a 172 mm robot need finer mapping
        # than the generic 5 cm room default.  Two centimetres matches the
        # absorbed Control mapper and preserves narrow openings without the
        # CPU/memory cost of the 5 mm navigation reference raster.
        "resolution": 0.02,
        "minimum_travel_distance": 0.08,
        "minimum_travel_heading": 0.10,
        "scan_buffer_size": 40,
        # Simulation /odom is published from the exact Gazebo model pose.
        # Repetitive 10 mm walls can make scan matching select a false nearby
        # alignment and bend an otherwise exact trajectory.  Rasterize live
        # scans at their authoritative odometric poses for deterministic SLAM.
        "use_scan_matching": False,
        "do_loop_closing": False,
        "transform_timeout": 0.5,
    })
    return {"/**": {"ros__parameters": params}}


def _nav_config(ns: str, rosy_nav_share: str,
                inflation_radius: float = 0.0) -> dict:
    """로봇별 nav2 파라미터.

    프레임 접두는 navigation 의 `apply_nav2_frame_prefix` 를 그대로 쓴다 — `map` 은
    전역으로 남기고 odom/base_* 만 `rosy_XX/` 로 바꾸는 규칙이 거기 한 곳에 있다.

    여기서 두 가지를 더 얹는다:
    - use_sim_time: 저장소 파일은 실기 기준이라 collision_monitor 등이 false 로 못박혀 있다.
    - 네임스페이스 루트 키: 노드의 완전한 이름은 `/rosy_XX/controller_server` 라, 파일
      최상위가 `controller_server` 면 매칭되지 않아 파라미터가 통째로 무시되고 nav2 가
      기본값으로 뜬다("No critics defined for FollowPath" 가 그 증상이다).
      nav2_bringup 의 RewrittenYaml(root_key=namespace) 과 같은 형태다.
    """
    from navigation.frame_prefix import apply_nav2_frame_prefix

    defaults_path = os.path.join(rosy_nav_share, "params", "nav2_params.yaml")
    with open(defaults_path, encoding="utf-8") as f:
        defaults = yaml.safe_load(f)

    def force_sim_time(value):
        if isinstance(value, dict):
            return {k: (True if k == "use_sim_time" else force_sim_time(v))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [force_sim_time(v) for v in value]
        return value

    params = force_sim_time(apply_nav2_frame_prefix(defaults, ns))
    if inflation_radius:
        # 통로 폭은 월드마다 다르고, 팽창 반경은 그 폭에 맞춰야 한다. 좁은 통로에서는
        # 반폭보다 크게 잡아야 경로가 중앙을 따라가고, 잡동사니가 빽빽한 방에서는
        # 작게 잡아야 출발조차 막히지 않는다. 한 값으로 둘 다 만족시킬 수 없다.
        for costmap in ("local_costmap", "global_costmap"):
            layer = params[costmap][costmap]["ros__parameters"]["inflation_layer"]
            layer["inflation_radius"] = inflation_radius

    # SmacPlanner2D searches x/y cells without a heading state.  A rectangular
    # footprint can therefore be accepted near a corner at yaw=0 even though
    # the controller must later rotate it through the corner; the next replan
    # then reports "Start occupied".  Only the planner's global costmap takes the padded
    # circumscribed radius; RPP's local check keeps the device footprint (D-395 R4).
    costmap_params = [
        params[name][name]["ros__parameters"]
        for name in ("local_costmap", "global_costmap")
    ]
    source_footprint = next(
        (item.get("footprint") for item in costmap_params if item.get("footprint")),
        None,
    )
    if source_footprint is not None:
        vertices = yaml.safe_load(source_footprint)
        padding = max(float(item.get("footprint_padding", 0.)) for item in costmap_params)
        circumscribed_radius = max(math.hypot(float(x), float(y)) for x, y in vertices) + padding
        for item in costmap_params[1:]:  # global_costmap only
            item.pop("footprint", None)
            item["robot_radius"] = circumscribed_radius
            item["footprint_padding"] = 0.

    # Simulation-only, reducing-only narrow-space trial. These values mirror the
    # reviewed map_260905 candidate: preserve footprint/inflation/collision
    # guards while reducing speed, lookahead and progress distance. Hardware
    # speed authority still requires a commissioning certificate.
    controller = params["controller_server"]["ros__parameters"]
    follow = controller["FollowPath"]
    follow["desired_linear_vel"] = min(float(follow["desired_linear_vel"]), .10)
    follow["use_velocity_scaled_lookahead_dist"] = True
    follow["lookahead_dist"] = .20
    follow["min_lookahead_dist"] = .15
    follow["max_lookahead_dist"] = .30
    follow["rotate_to_heading_angular_vel"] = min(
        float(follow["rotate_to_heading_angular_vel"]), .40)
    follow["min_approach_linear_velocity"] = min(
        float(follow["min_approach_linear_velocity"]), .03)
    follow["regulated_linear_scaling_min_speed"] = min(
        float(follow["regulated_linear_scaling_min_speed"]), .03)
    follow["use_regulated_linear_velocity_scaling"] = True
    follow["use_cost_regulated_linear_velocity_scaling"] = True
    follow["cost_scaling_gain"] = min(float(follow["cost_scaling_gain"]), 1.0)
    local_inflation = params["local_costmap"]["local_costmap"]["ros__parameters"]["inflation_layer"]
    follow["cost_scaling_dist"] = min(
        float(follow["cost_scaling_dist"]), float(local_inflation["inflation_radius"]))
    follow["inflation_cost_scaling_factor"] = float(local_inflation["cost_scaling_factor"])
    controller["progress_checker"]["required_movement_radius"] = min(
        float(controller["progress_checker"]["required_movement_radius"]), .05)
    # D-395 R4: RPP only rotates while its carrot (~min_lookahead ahead) is within xy_goal_tolerance.
    tol = controller["general_goal_checker"]
    tol["xy_goal_tolerance"] = min(float(tol["xy_goal_tolerance"]), .10)

    smoother = params["velocity_smoother"]["ros__parameters"]
    smoother["max_velocity"] = [
        min(float(smoother["max_velocity"][0]), .10),
        0.,
        min(float(smoother["max_velocity"][2]), .50),
    ]
    smoother["min_velocity"] = [
        max(float(smoother["min_velocity"][0]), -.10),
        0.,
        max(float(smoother["min_velocity"][2]), -.50),
    ]
    return {ns: params}


def _launch_setup(context):
    robots = int(LaunchConfiguration("robots").perform(context))
    prefix = LaunchConfiguration("prefix").perform(context)
    world_name = LaunchConfiguration("world_name").perform(context)
    mode = LaunchConfiguration("mode").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() in ("true", "1")
    core = LaunchConfiguration("core").perform(context).lower() in ("true", "1")
    api_port_base = int(LaunchConfiguration("api_port_base").perform(context))
    map_yaml = LaunchConfiguration("map").perform(context)
    loc_assist = LaunchConfiguration("loc_assist").perform(context).lower() in ("true", "1")
    # bare-context 단위 시험에서도 돌아간다: 선언되지 않은 launch configuration 은
    # LaunchConfiguration.perform 가 아닌 dict 조회로 기본값을 받는다.
    run_spec = _load_run_spec(context.launch_configurations.get("run_spec", ""))
    spawn_spacing_raw = LaunchConfiguration("spawn_spacing").perform(context)
    profile = resolve_world(
        world_name,
        inflation_radius=_optional_float(LaunchConfiguration("inflation_radius").perform(context)),
        spawn_x=_optional_float(LaunchConfiguration("spawn_x").perform(context)),
        spawn_y=_optional_float(LaunchConfiguration("spawn_y").perform(context)),
        spawn_spacing=_optional_float(spawn_spacing_raw),
        map_yaml=map_yaml.strip() or None,
    )
    spawn_poses = parse_spawn_poses(LaunchConfiguration("spawn_poses").perform(context), robots)
    spawn_x = profile.spawn_x
    spawn_y = profile.spawn_y
    spacing = profile.spawn_spacing
    inflation_radius = profile.inflation_radius

    gz_sim_share = get_package_share_directory("ros_gz_sim")
    rosy_gz_share = get_package_share_directory("gz_sim")
    rosy_nav_share = get_package_share_directory("navigation")
    rosy_desc_share = get_package_share_directory("description")
    if not (map_yaml or "").strip() and profile.map:
        map_yaml = str(resolve_asset_path(
            profile.map,
            os.path.join(rosy_nav_share, "map"),
            package_share=get_package_share_directory,
        ))
    else:
        map_yaml = (map_yaml or "").strip()

    actions = [
        SetEnvironmentVariable("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp"),
        SetEnvironmentVariable("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST"),
        SetEnvironmentVariable(
            "GZ_SIM_RESOURCE_PATH",
            os.path.join(rosy_desc_share, "..")
            + ":" + os.path.join(rosy_gz_share, "models")
            + ":" + os.path.join(os.environ.get("HOME", ""), ".gazebo", "models")
            + world_share_parent(profile, get_package_share_directory),
        )
    ]
    if run_spec:
        # D-426: 같은 고유 partition을 모든 Gazebo 참여 프로세스에 전달한다(계획 규칙 2).
        actions.append(SetEnvironmentVariable("GZ_PARTITION", str(run_spec["gz_partition"])))

    # per-robot bridge config를 런치 시점 생성 (physics_step 의 월드 사본도 여기)
    bridge_dir = tempfile.mkdtemp(prefix="rosy_gz_multi_")
    world_path, speed_env = apply_sim_speed(str(resolve_world_path(
        profile,
        rosy_gz_share,
        package_share=get_package_share_directory,
    )), context, bridge_dir)
    actions += speed_env

    # Gazebo 서버 (1회) — headless 여부로 GUI 분기
    server_args = f"-r -s -v4 \"{world_path}\""
    actions.append(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(gz_sim_share, "launch", "gz_sim.launch.py")
            ),
            launch_arguments={"gz_args": server_args, "on_exit_shutdown": "true"}.items(),
        )
    )
    if not headless:
        actions.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(gz_sim_share, "launch", "gz_sim.launch.py")
                ),
                launch_arguments={"gz_args": "-g -v4"}.items(),
            )
        )

    for i in range(1, robots + 1):
        ns = f"{prefix}_{i:02d}"
        group_actions = []

        # 1) robot_state_publisher (namespace + frame_prefix)
        group_actions.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(rosy_desc_share, "launch", "upload_robot.launch.py")
                ),
                launch_arguments={
                    "namespace": ns,
                    "is_sim": "True",
                }.items(),
            )
        )

        # 2) spawn — spawn_x/spawn_y 에서 x축으로 spacing 간격 배치
        x, y, spawn_yaw = spawn_poses[i - 1] if spawn_poses else (*spawn_xy(i, spawn_x, spawn_y, spacing), 0.)
        group_actions.append(
            Node(
                package="ros_gz_sim",
                executable="create",
                name=f"create_{ns}",
                output="screen",
                arguments=[
                    "-name", ns,
                    "-topic", f"{ns}/robot_description",
                    "-x", str(x), "-y", str(y), "-z", "0.1", "-Y", str(spawn_yaw),
                ],
                parameters=[{"use_sim_time": True}],
            )
        )

        # 3) per-robot bridge (1번 로봇이 clock 담당)
        config_path = os.path.join(bridge_dir, f"bridge_{ns}.yaml")
        with open(config_path, "w") as f:
            yaml.safe_dump(_bridge_config(f"{ns}/", with_clock=(i == 1)), f)
        group_actions.append(
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name=f"bridge_{ns}",
                output="screen",
                arguments=["--ros-args", "-p", f"config_file:={config_path}"],
            )
        )

        # 4) Nav2 / SLAM (mode). Wait in wall time, not simulation time. Gazebo
        # can advance five simulated seconds before its rendering sensors have
        # finished initializing; starting slam_toolbox in that interval misses
        # its lifecycle transition and leaves a 0x0 map until a manual reset.
        mode_actions = []
        if mode == "nav":
            nav_cfg = os.path.join(bridge_dir, f"nav2_{ns}.yaml")
            with open(nav_cfg, "w", encoding="utf-8") as f:
                yaml.safe_dump(_nav_config(ns, rosy_nav_share, inflation_radius),
                               f, sort_keys=False)
            nav_args = {
                "namespace": ns,
                "params_file": nav_cfg,
                # Localization and navigation otherwise issue concurrent load
                # requests to one component container. Under constrained field
                # hosts that race can abort the manager before /load_node exists.
                "use_composition": "False",
            }
            apply_nav_composition(nav_args, context)
            if map_yaml:
                nav_args["map"] = map_yaml
            mode_actions.append(
                IncludeLaunchDescription(
                    AnyLaunchDescriptionSource(
                        os.path.join(rosy_nav_share, "launch", "gz_bringup_launch.xml")
                    ),
                    launch_arguments=nav_args.items(),
                )
            )
            if loc_assist:  # D-395 P2-3: power-on is UNKNOWN; the seeded AMCL pose is not evidence
                mode_actions.append(IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
                    get_package_share_directory("control"), "launch", "loc_assist.launch.py")),
                    launch_arguments={"namespace": ns, "use_sim_time": "true", "map_yaml": map_yaml}.items()))
        elif mode in ("slam", "slam_nav"):
            slam_cfg = os.path.join(bridge_dir, f"mapper_{ns}.yaml")
            with open(slam_cfg, "w", encoding="utf-8") as f:
                yaml.safe_dump(_slam_config(ns, rosy_nav_share), f, sort_keys=False)
            mode_actions.append(
                GroupAction([
                    PushRosNamespace(ns),
                    # slam_toolbox 는 맵을 절대 토픽 `/map`·`/map_metadata` 로 발행한다
                    # (네임스페이스를 push 해도 따라오지 않는다). N대를 띄우면 전부 같은
                    # 토픽에 겹쳐 쓴다 — 로봇별로 되돌려 준다.
                    SetRemap("/map", f"/{ns}/map"),
                    SetRemap("/map_metadata", f"/{ns}/map_metadata"),
                    IncludeLaunchDescription(
                        AnyLaunchDescriptionSource(
                            os.path.join(rosy_nav_share, "launch", "gz_map_building.launch.xml")
                        ),
                        launch_arguments={
                            "use_sim_time": "True",
                            "slam_params_file": slam_cfg,
                        }.items(),
                    ),
                ])
            )
            if mode == "slam_nav":
                # 맵을 만들면서 그 맵 위로 주행한다. map_server 와 amcl 은 띄우지 않는다
                # — map→odom 은 slam_toolbox 가 낸다. 이 조합이 없으면 좁은 통로 월드는
                # 순환에 걸린다: 맵이 없어 nav2 를 못 쓰고, nav2 없이 몰면 로봇이 벽에
                # 끼고, 끼면 바퀴가 헛돌아 odom 이 폭주하고, 그 odom 으로 뜬 맵은 못 쓴다.
                nav_cfg = os.path.join(bridge_dir, f"nav2_{ns}.yaml")
                with open(nav_cfg, "w", encoding="utf-8") as f:
                    yaml.safe_dump(_nav_config(ns, rosy_nav_share, inflation_radius),
                                   f, sort_keys=False)
                mode_actions.append(
                    GroupAction([
                        PushRosNamespace(ns),
                        IncludeLaunchDescription(
                            AnyLaunchDescriptionSource(
                                os.path.join(rosy_nav_share, "launch", "navigation_launch.xml")
                            ),
                            launch_arguments={
                                "params_file": nav_cfg,
                                "use_sim_time": "True",
                                "autostart": "True",
                                "use_composition": "False",
                            }.items(),
                        ),
                    ])
                )

        # 5) map 시드 — odom (0,0) 을 관제 pose 로 쓰지 않는다 (D-115)
        if mode_actions:
            group_actions.append(TimerAction(period=15.0, actions=mode_actions))

        if mode == "nav" and LaunchConfiguration("seed_initialpose").perform(context).lower() == "true":
            group_actions.append(
                Node(
                    package="gz_sim",
                    executable="seed_initialpose.py",
                    name="seed_initialpose",
                    namespace=ns,
                    output="screen",
                    parameters=[{
                        "use_sim_time": True,
                        "x": x,
                        "y": y,
                        "yaw": spawn_yaw,
                    }],
                )
            )

        # 6) core (core:=true) — 로봇마다 포트·HOME·설정을 가른다.
        #    HOME 을 가르는 이유: waypoints.json 과 audit.jsonl 이 Path.home()/.rosy 에
        #    고정돼 있어, 같은 HOME 이면 N대가 한 파일을 쓴다.
        #    HOME 을 가르면 ROS 로그도 따라간다: 각 코어의 ~/.ros/log 는 그 임시 HOME
        #    아래에 생기므로(ROS_LOG_DIR 기본값이 $HOME/.ros/log), 로그는 로봇마다
        #    나뉘고 런치가 끝나도 사용자의 ~/.ros 를 어지럽히지 않는다.
        if core:
            if run_spec:
                # D-426 T1: 검증 runner 소유 오버레이를 그대로 쓴다(fleet.hub_url·
                # pairing_token·auth 토큰은 runner가 run별로 만들었다). 여기서 다시
                # 쓰지 않는다 — 토큰 불일치가 곧 READY 거절 사유이기 때문이다.
                core_cfg = _run_spec_overlay(run_spec, ns)
                core_home = os.path.join(run_spec["core_config_dir"], f"home_{ns}")
            else:
                core_home = os.path.join(bridge_dir, f"home_{ns}")
                core_cfg = os.path.join(bridge_dir, f"rosy_{ns}.yaml")
                with open(core_cfg, "w") as f:
                    yaml.safe_dump(_core_config(ns, api_port_base + i - 1), f)
            os.makedirs(core_home, exist_ok=True)
            group_actions.append(
                Node(
                    package="core",
                    executable="core",
                    name="core",
                    namespace=ns,
                    output="screen",
                    parameters=[{"use_sim_time": True}],
                    additional_env={
                        "ROSY_NAMESPACE": ns,
                        "ROSY_CONFIG": core_cfg,
                        "HOME": core_home,
                        # D-426: run_spec 사용 시 토큰은 오버레이 안에 있다(런타임 생성).
                        **({} if run_spec else {"ROSY_DEV_AUTH": "1"}),
                    },
                )
            )

        actions.extend(group_actions)

    if core:
        if run_spec:
            # D-426: robots.yaml 은 runner가 이미 만들었다(페어링 토큰 포함). 이중 생성 금지.
            actions.append(LogInfo(msg=f"fleet robots.yaml (runner-owned): {run_spec['fleet_manifest']}"))
        else:
            namespaces = [f"{prefix}_{i:02d}" for i in range(1, robots + 1)]
            manifest_path = os.path.join(bridge_dir, "robots.yaml")
            with open(manifest_path, "w") as f:
                yaml.safe_dump({"robots": _robots_manifest(namespaces, api_port_base)}, f, sort_keys=False)
            try:
                # 이 파일은 운영자 토큰을 담는다. mkdtemp 은 디렉터리를 0700 으로 만들지만
                # 파일 자체는 umask 를 따르므로, fleet 이 경고하는 것과 같은 조건을
                # 우리가 먼저 만들지 않는다. Windows 는 이 비트를 무시한다.
                os.chmod(manifest_path, 0o600)
            except OSError as exc:
                actions.append(LogInfo(msg=f"could not restrict robots.yaml permissions: {exc}"))
            actions.append(LogInfo(msg=f"fleet robots.yaml: {manifest_path}"))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("robots", default_value="2",
                              description="로봇 대수"),
        DeclareLaunchArgument("prefix", default_value="rosy",
                              description="namespace 접두 (rosy → rosy_01, rosy_02, ...)"),
        DeclareLaunchArgument("world_name", default_value="rosy_factory.world"),
        DeclareLaunchArgument("mode", default_value="none",
                              choices=["none", "nav", "slam", "slam_nav"],
                              description="로봇별 상위 스택. none=spawn만, nav=기존 맵 주행, "
                                          "slam=맵 작성만, slam_nav=맵을 만들면서 그 맵 위로 주행"),
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("inflation_radius", default_value="",
                              description="비면 config/worlds.yaml. 숫자면 그 월드만 덮어쓴다"),
        DeclareLaunchArgument("spawn_x", default_value="",
                              description="비면 월드 카탈로그"),
        DeclareLaunchArgument("spawn_y", default_value="",
                              description="비면 월드 카탈로그"),
        DeclareLaunchArgument("spawn_spacing", default_value="",
                              description="로봇 간 x축 배치 간격 (m). 비우면 월드 프로필 값 "
                                          "(config/worlds.yaml), 그것도 없으면 1.5"),
        DeclareLaunchArgument("spawn_poses", default_value="", description="'x,y,yaw_rad;..' 로봇별"),
        DeclareLaunchArgument("seed_initialpose", default_value="true", description="false: AMCL 시드 없음"),
        DeclareLaunchArgument("core", default_value="false",
                              description="로봇별 core 기동 (포트 api_port_base + i - 1)"),
        DeclareLaunchArgument("map", default_value="",
                              description="mode:=nav 맵 yaml. 비면 월드 카탈로그"),
        DeclareLaunchArgument("loc_assist", default_value="true", choices=["true", "false"],
                              description="mode:=nav 에서 로봇별 D-395 loc_assist_node"),
        nav_composition_argument(),
        *sim_speed_arguments(),
        DeclareLaunchArgument("api_port_base", default_value="8080",
                              description="첫 로봇의 core API 포트"),
        DeclareLaunchArgument("run_spec", default_value="",
                              description="D-426 검증 runner 소유 run_spec.yaml 경로. "
                                          "비우면 기존 자체 생성 동작(임시 디렉터리·개발 토큰)"),
        OpaqueFunction(function=_launch_setup),
    ])
