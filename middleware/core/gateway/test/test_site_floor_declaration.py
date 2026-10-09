"""D-507 9: line_follow.site_floor_map_id, the one site floor declaration per map."""
from dataclasses import replace

import pytest

from core.line_follow_wiring import _line_follow_config, check_bridge_floor_basis
from core_features.line_follow import LineFollowConfig

BODY = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06, body_lidar_x_m=0.,
            body_rotation_radius_m=.1)
SITE = dict(BODY, ir_guard_enabled=True, obstacle_mode='path')
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def test_default_is_null():
    assert LineFollowConfig().site_floor_map_id is None
    assert _line_follow_config({}).site_floor_map_id is None


@pytest.mark.parametrize('map_id', ['lab-a', 'map_v2_fleet.260919', 'A' * 64, '0'])
def test_a_site_map_id_is_accepted(map_id):
    assert LineFollowConfig(site_floor_map_id=map_id, **SITE).site_floor_map_id == map_id


@pytest.mark.parametrize('map_id', ['site', '', 'A' * 65, 'lab a', 'lab/a', 'läb', 7, True])
def test_bad_format_and_the_default_map_id_are_refused(map_id):
    with pytest.raises(ValueError, match='site_floor_map_id'):
        LineFollowConfig(site_floor_map_id=map_id, **SITE)


@pytest.mark.parametrize('missing', [dict(ir_guard_enabled=False), dict(obstacle_mode='sector'),
                                     dict(body_front_x_m=None), dict(body_lidar_x_m=None),
                                     dict(body_rotation_radius_m=None)])
def test_each_prerequisite_is_required(missing):
    with pytest.raises(ValueError, match='site_floor_map_id'):
        LineFollowConfig(site_floor_map_id='lab-a', **{**SITE, **missing})


@pytest.mark.parametrize('old', ['bridge_site_no_dropoffs', 'junction_turn_site_accepted'])
@pytest.mark.parametrize('value', [True, False])
def test_removed_keys_refuse_start_naming_the_new_key(old, value):
    with pytest.raises(ValueError, match=f'{old}.*site_floor_map_id'):
        _line_follow_config({**SITE, old: value, 'site_floor_map_id': 'lab-a'})


def test_removed_key_in_a_later_layer_refuses_start():
    """Config layers merge into one line_follow dict: a site overlay's old key survives it."""
    from core_common.config import _deep_merge
    merged = _deep_merge({'line_follow': {'site_floor_map_id': None}},
                         {'line_follow': {'junction_turn_site_accepted': True}})
    with pytest.raises(ValueError, match='site_floor_map_id'):
        _line_follow_config(merged['line_follow'])


@pytest.mark.parametrize('map_id, mode, ok', [
    ('lab-a', 'off', True), ('lab-a', 'shadow', True), (None, 'enforce', True),
    (None, 'off', False), (None, 'shadow', False)])
def test_bridge_floor_basis_is_enforce_or_the_declaration(map_id, mode, ok):
    config = LineFollowConfig(bridge_enabled=True, site_floor_map_id=map_id, **SITE)
    if ok:
        check_bridge_floor_basis(config, mode)
    else:
        with pytest.raises(ValueError, match='site_floor_map_id'):
            check_bridge_floor_basis(config, mode)


def test_capability_shows_the_declaration(core_client):
    client, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)  # odometry: CAP-001 announces the base

    def base():
        response = client.get("/api/v1/system/capabilities", headers=VIEWER)
        assert response.status_code == 200
        return response.json()["controls"]["items"][0]

    assert 'site_floor_map_id' not in base()  # null leaves the optional field out
    lf = svc.line_follow
    lf._config = replace(lf.config, site_floor_map_id='lab-a', **SITE)
    assert base()['site_floor_map_id'] == 'lab-a'
