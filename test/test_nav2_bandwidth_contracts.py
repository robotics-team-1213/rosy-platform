"""Nav2 가 내보내는 양은 그것을 읽는 쪽에 맞춰져 있어야 한다는 계약.

이 파일이 있는 이유: `nav2_params.yaml` 의 발행 주기에는 **어떤 테스트도 걸려
있지 않았다**. `publish_frequency` 를 저장소 전체에서 grep 하면 그 params 파일
자신 말고는 나오지 않는다. 그래서 global costmap 이 소비자보다 다섯 배 빠르게,
브라우저가 없어도, 전체 격자를 계속 내보내고 있었다.

숫자의 출처는 측정이 아니라 소비자다 — `src/rosy_core/rosy_core/web/app.js:647`
의 `refreshSlowData` 가 5000 ms 간격이므로 0.2 Hz 다. 위쪽 upstream Nav2 파일을
머지하다 기본값이 되돌아오면 여기서 깨진다.

`params_rewrite` 왕복도 함께 본다. 런치는 원본이 아니라 네임스페이스가 입혀진
사본으로 뜨므로(`hardware.launch.py`), 원본만 검사하면 실제로 로봇에 적용되는
파일은 검증되지 않은 채로 남는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from robot_contracts import NAV_PARAMS, ROOT

_PKG = str(ROOT / "middleware" / "drive" / "planning" / "nav2")
if _PKG not in sys.path:
    sys.path.append(_PKG)

#: 대시보드 폴링 간격 5000 ms → 0.2 Hz. app.js:647 이 바뀌면 이 값도 같이 바뀐다.
CONSUMER_POLL_HZ = 0.2

COSTMAPS = ("local_costmap", "global_costmap")


def _params(source=NAV_PARAMS):
    return yaml.safe_load(source.read_text(encoding="utf-8"))


def _costmap(params, name):
    section = params.get(name)
    if section is None:
        # namespaced rewrite prefixes top-level sections (D-4): `/rosy_02/local_costmap`
        section = next(value for key, value in params.items() if key.endswith(f"/{name}"))
    return section[name]["ros__parameters"]


@pytest.mark.parametrize("name", COSTMAPS)
def test_publish_rate_matches_the_dashboard_poll(name):
    costmap = _costmap(_params(), name)
    assert costmap["publish_frequency"] <= CONSUMER_POLL_HZ, (
        f"{name} publishes faster than anything reads it; the only consumer is "
        f"web/app.js:647's 5 s poll"
    )


@pytest.mark.parametrize("name", COSTMAPS)
def test_publishing_never_outpaces_updating(name):
    """발행이 갱신보다 빠르면 같은 격자를 두 번 보낸다."""
    costmap = _costmap(_params(), name)
    assert costmap["publish_frequency"] <= costmap["update_frequency"]


def test_local_costmap_uses_2d_obstacle_layer_without_voxel_layer():
    """Pi 5 20 Hz 루프 보호: local_costmap 은 3D voxel 대신 2D ObstacleLayer 만 쓴다."""
    local = _costmap(_params(), "local_costmap")
    assert "voxel_layer" not in local["plugins"] and "voxel_layer" not in local
    assert "obstacle_layer" in local["plugins"]
    assert local["obstacle_layer"]["plugin"] == "nav2_costmap_2d::ObstacleLayer"


@pytest.mark.parametrize("name", COSTMAPS)
def test_full_costmaps_are_still_sent_whole(name):
    """가드레일.

    델타 전송으로 바꾸는 것은 별도 작업이다 — `ros_bridge` 가 `costmap_updates`
    를 구독하지 않으므로, 여기만 뒤집으면 대시보드 맵이 조용히 멈춘다.
    """
    costmap = _costmap(_params(), name)
    assert costmap["always_send_full_costmap"] is True, (
        "flipping this without a costmap_updates subscriber stops the map panel"
    )


def test_the_rewritten_file_launch_actually_uses_keeps_the_rates(tmp_path):
    """런치는 원본이 아니라 이 사본으로 뜬다.

    `params_rewrite` 는 safe_load → 변형 → safe_dump 라서 구조적으로는 키를
    보존하지만, 그것을 확인하는 테스트가 없었다.
    """
    from navigation.params_rewrite import write_prefixed_nav2_params

    written = write_prefixed_nav2_params(NAV_PARAMS, "rosy_02", directory=str(tmp_path))
    rewritten = _params(Path(written))

    for name in COSTMAPS:
        costmap = _costmap(rewritten, name)
        assert costmap["publish_frequency"] <= CONSUMER_POLL_HZ
        assert costmap["always_send_full_costmap"] is True
    local = _costmap(rewritten, "local_costmap")
    assert "voxel_layer" not in local and local["obstacle_layer"]["plugin"] == "nav2_costmap_2d::ObstacleLayer"


BOND_LIFECYCLE_NODES = (
    "amcl",
    "map_server",
    "bt_navigator",
    "controller_server",
    "planner_server",
    "smoother_server",
    "behavior_server",
    "waypoint_follower",
    "velocity_smoother",
)


@pytest.mark.parametrize("node_name", BOND_LIFECYCLE_NODES)
def test_nav2_bond_heartbeat_disabled_in_params_and_rewrite(tmp_path, node_name):
    from navigation.params_rewrite import write_prefixed_nav2_params

    raw = _params()
    assert raw[node_name]["ros__parameters"]["bond_heartbeat_period"] == 0.0
    written = write_prefixed_nav2_params(NAV_PARAMS, "rosy_02", directory=str(tmp_path))
    rewritten = _params(Path(written))
    assert rewritten[f"/rosy_02/{node_name}"]["ros__parameters"]["bond_heartbeat_period"] == 0.0


@pytest.mark.parametrize("launch_name", ("navigation_launch.xml", "localization_launch.xml"))
def test_nav2_lifecycle_manager_disables_bond_timeout_by_default(launch_name):
    import xml.etree.ElementTree as ET

    xml = ROOT / "middleware" / "drive" / "planning" / "nav2" / "launch" / launch_name
    tree = ET.parse(xml).getroot()
    arg = next(a for a in tree.findall("arg") if a.attrib.get("name") == "bond_timeout")
    assert arg.attrib.get("default") == "0.0"
    mgr_elems = [
        el for el in tree.iter()
        if el.tag in ("composable_node", "node")
        and (el.attrib.get("name") or "").startswith("lifecycle_manager_")
    ]
    assert len(mgr_elems) == 2
    for mgr in mgr_elems:
        params = {p.attrib["name"]: p.attrib["value"] for p in mgr.findall("param") if "name" in p.attrib}
        assert params.get("bond_timeout") == "$(var bond_timeout)"
