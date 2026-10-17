"""AMCL initial pose must carry variance or the filter ignores the click."""

from pathlib import Path

from core_features.maps import occupancy_map_id
from core_features.navigation.initial_pose import amcl_pose_covariance

GRID = {
    "width": 2,
    "height": 2,
    "resolution": 0.05,
    "origin": {"x": -1.0, "y": -0.5, "yaw": 0.0},
    "data": [0, 100, -1, 50],
}


def test_amcl_initial_pose_covariance_is_not_all_zeros():
    cov = amcl_pose_covariance()
    assert len(cov) == 36
    assert cov[0] > 0
    assert cov[7] > 0
    assert cov[35] > 0
    assert sum(cov) == cov[0] + cov[7] + cov[35]


def test_ros_bridge_publishes_amcl_covariance():
    text = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "bridge"
        / "ros_bridge.py"
    ).read_text(encoding="utf-8")
    assert "amcl_pose_covariance" in text
    assert "msg.pose.covariance" in text


def test_map_callback_preserves_saved_id_and_refreshes_unsaved_id(core_client):
    from types import SimpleNamespace as NS
    from core.bridge.map_observation import receive_map
    for initial in (None, 'occupancy:old', 'saved-map'):
        _, svc = core_client()
        svc.state.set_map_id(initial)
        msg = NS(info=NS(width=2, height=2, resolution=.05,
            origin=NS(position=NS(x=-1., y=-.5), orientation=NS(x=0., y=0., z=0., w=1.))),
            data=list(GRID['data']))
        assert receive_map(NS(_svc=svc, _map_pose_lease=None), msg, warn=lambda _: None)
        assert svc.state.map_id == ('saved-map' if initial == 'saved-map' else occupancy_map_id(GRID))


def test_ros_map_and_lifecycle_callbacks_delegate_to_the_observed_source_adapter():
    import ast
    tree = ast.parse((Path(__file__).parents[1] / 'core/bridge/ros_bridge.py').read_text(encoding='utf-8'))
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for method, target in (('_on_map', 'map_observation.receive_map'),
                           ('_on_map_server_transition', 'map_observation.lifecycle'),
                           ('_on_slam_transition', 'map_observation.lifecycle')):
        assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == target
                   for node in ast.walk(methods[method]))


def test_occupancy_map_id_changes_with_grid_content():
    other = dict(GRID, data=[0, 0, 0, 0])
    assert occupancy_map_id(GRID).startswith("occupancy:")
    assert occupancy_map_id(GRID) != occupancy_map_id(other)
    assert occupancy_map_id(GRID) == occupancy_map_id(dict(GRID))
