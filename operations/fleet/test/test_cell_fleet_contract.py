from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.charge_bay_routes import install_charge_bay_routes
from fleet.server.pipeline_routes import install_pipeline_routes

from fleet.pipeline.cell_fleet_contract import (
    CellToFleetRReceipt,
    FleetRToCellHandoff,
    evaluate_handoff_gate,
    validate_boundary_separation,
)


def _handoff(**changes):
    values = dict(
        handoff_lease_id='lease-1', site_id='site-1', map_version=3,
        station_place='S3', cell_id='cell_s', robot_id='amr-1',
        robot_kind='pinky_pro', station_pose_xy_yaw=(1.0, 2.0, 0.5),
    )
    return FleetRToCellHandoff(**(values | changes))


def _receipt(phase='IDLE', **changes):
    values = dict(
        handoff_lease_id='lease-1', cell_id='cell_s', station_place='S3',
        robot_id='amr-1', phase=phase,
    )
    return CellToFleetRReceipt(**(values | changes))


def test_handoff_and_receipt_are_frozen_and_serialize():
    handoff = _handoff(cargo_manifest=('bin-1',))
    receipt = _receipt('RELEASED', stage_id='stage-1')
    assert handoff.to_dict()['cargo_manifest'] == ('bin-1',)
    assert receipt.to_dict()['stage_id'] == 'stage-1'
    with pytest.raises(FrozenInstanceError):
        handoff.site_id = 'other'


@pytest.mark.parametrize('changes', [
    {'wheel_brake_locked': False}, {'v_cmd_mps': 0.01},
])
def test_unbraked_or_moving_amr_denies_claim(changes):
    assert not evaluate_handoff_gate(_handoff(**changes), None)['cell_can_claim']


@pytest.mark.parametrize('phase', ['CLAIMED', 'ARM_IN_BED_ZONE'])
def test_active_cell_phases_inhibit_amr_motion(phase):
    gate = evaluate_handoff_gate(_handoff(), _receipt(phase))
    assert gate['amr_motion_inhibited'] and not gate['amr_can_depart']


def test_released_amr_can_depart():
    gate = evaluate_handoff_gate(_handoff(), _receipt('RELEASED'))
    assert not gate['amr_motion_inhibited'] and gate['amr_can_depart']


def test_boundary_separation_detects_cross_domain_keys():
    bad = validate_boundary_separation(
        fleet_r_keys=['road_nav2', 'gripper_pinch'],
        cell_keys=['arm_s', 'traffic_signals'],
    )
    assert not bad['valid']
    assert bad['fleet_r_violations'] == ['gripper_pinch']
    assert bad['fleet_cell_violations'] == ['traffic_signals']
    assert validate_boundary_separation(['road_nav2'], ['arm_s'])['valid']


def test_end_to_end_bay_departure_to_s3_omx_cell_contract_handoff(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.sim.bay_departure_sim import (
        build_world_261026_site_map,
        run_s3_cell_contract_handoff,
    )

    site, graph, bays = build_world_261026_site_map()
    result = run_s3_cell_contract_handoff(site, graph, bays, work_dir=str(tmp_path))
    assert 'loop_left' in result['s3_route_edges']
    assert 'lower_east' in result['s3_route_edges']
    assert 'loop_right' in result['s3_route_edges']
    assert result['s3_route_places'] == ['J_out', 'S4', 'S5', 'S3']
    assert sorted(result['stop_lines']) == ['S1', 'S2', 'S3', 'S4', 'S5']
    assert result['selective_pit_in']['circulating_robot']['places'] == ['J_in', 'J_out']
    assert 'S2' in result['selective_pit_in']['pit_in_robot']['places']
    assert result['inhibited_gate']['amr_motion_inhibited'] is True
    assert result['omx_receipt']['phase'] == 'RELEASED'
    assert result['omx_receipt']['amr_motion_inhibited'] is False
    assert result['omx_receipt']['goal_evidence_digest'].startswith('sha256:')
    assert result['released_v_cmd_mps'] > 0.0


def test_remote_fleet_r_cross_pc_handoff_lifecycle(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / "tools/sim/bay_departure_sim.py").is_file()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.sim.bay_departure_sim import build_world_261026_site_map, run_s3_cell_contract_handoff

    site, graph, bays = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps

    async def gathered():
        return {'robots': []}

    install_charge_bay_routes(app, SimpleNamespace(_clock=lambda: 0.0), gathered, ())
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)
    calls = []

    def request_fn(method, path, body):
        calls.append((method, path, body))
        response = client.request(method, path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    result = run_s3_cell_contract_handoff(
        site, graph, bays, work_dir=str(tmp_path), fleet_r_url='https://fleet-r.test',
        request_fn=request_fn,
    )['remote_fleet_r_handoff']
    assert [method for method, _, _ in calls] == ['POST', 'GET', 'GET', 'POST']
    assert calls[0][2]['phase'] == 'ARM_IN_BED_ZONE'
    assert calls[-1][2]['phase'] == 'RELEASED'
    assert calls[-1][2]['goal_evidence_digest'] == result['omx_receipt']['goal_evidence_digest']
    assert result['claim_gate']['amr_motion_inhibited'] is True
    assert result['charge_bays_locked']['amr_motion_inhibited'] is True
    assert result['omx_receipt']['phase'] == 'RELEASED'
    assert result['release_gate']['amr_can_depart'] is True
    assert client.get('/api/fleet/pipeline/status').json()['omx_cell_layer']['cells']['cell_s']['gate']['amr_motion_inhibited'] is False
    assert client.get('/api/fleet/charge-bays').json()['omx_cells']['cell_s']['gate']['amr_motion_inhibited'] is False
