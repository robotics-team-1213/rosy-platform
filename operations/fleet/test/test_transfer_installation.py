"""D-927 C3: one installation file gives the owner, Fleet and the observer the same transfer."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'tools/sim/{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def tool():
    return _load('transfer_installation')


@pytest.fixture(scope='module')
def written(tool):
    return tool.document(tool.load())


def test_the_policy_seals_the_owner_catalog_and_the_digest_is_stable(tool, written):
    installed = tool.bindings(tool.load())
    assert written['policy']['catalog_digest'] == installed.catalog.digest
    assert written['policy']['bindings_digest'] == installed.revision
    assert tool.document(tool.load())['policy_digest'] == written['policy_digest']
    assert set(installed.catalog.poses) == {'source', 'target'}
    assert written['bases'] == {'omx_cell_sim_01': {'position_m': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}}


def test_the_source_pose_is_where_the_sim_world_puts_the_block(written):
    world = _load('omx_cell_world')
    block = next(box for box in world.boxes() if box['name'] == 'infeed_block')
    source = written['policy']['source_pose']
    assert math.dist(source['position_m'], block['pos']) < 1e-6
    yaw = 2 * math.atan2(source['orientation_xyzw'][2], source['orientation_xyzw'][3])
    assert abs(yaw - block['rpy'][2]) < 1e-6


def test_the_arm_at_home_leaves_both_zones_clear(tool, written):
    from fleet.server.evidence.physical_transfer_evidence import PhysicalTransferPolicy, _outside
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
    from omx_adapter.pose_plan import CellPlanningProfile
    from rosy.world.state.projections.physical_transfer import Bounds3
    observer = _load('transfer_observer')
    policy = PhysicalTransferPolicy.model_validate(written['policy'])
    profile = CellPlanningProfile.load(ROOT / 'deploy/robot/omx/sim/cell_profile.yaml')
    kin = OmxKinematics.load()
    home = TopDownPose(*tool._home(tool.load()))
    positions = dict(zip(ARM_JOINTS, kin.solve_top_down(home, profile.ik_limits()).joints))
    positions[profile.gripper_joint] = profile.gripper_open
    links = observer.ArmModel.load(tool.ASSETS).links(positions, {}, written['bases']['omx_cell_sim_01'])
    for name, link in links.items():
        bounds = Bounds3(link['bounds']['min_m'], link['bounds']['max_m'])
        assert all(_outside(bounds, zone, policy.zone_margin_m) for zone in policy.zones), name


def test_the_owner_side_refuses_a_file_from_another_catalog(tool, written, tmp_path, monkeypatch):
    path = tmp_path / 'installation.json'
    path.write_text(json.dumps(written), encoding='utf-8')
    monkeypatch.setenv('ROSY_ARM_TRANSFER_INSTALLATION', str(path))
    installed = tool.owner_installation_from_environment()
    assert installed.resource_policy_digest == written['policy_digest']
    path.write_text(json.dumps({**written, 'policy': {**written['policy'], 'catalog_digest': 'e' * 64}}),
                    encoding='utf-8')
    with pytest.raises(ValueError, match='another catalog'):
        tool.owner_installation_from_environment()
    monkeypatch.delenv('ROSY_ARM_TRANSFER_INSTALLATION')
    assert tool.owner_installation_from_environment() is None


def test_fleet_completes_the_installation_from_the_owner_capability(tool, written, tmp_path):
    from omx_adapter.action_api import ActionApi, UnixActionServer
    installed = tool.owner_installation(tool.load(), written['policy_digest'])
    catalog = installed.bindings.catalog
    capability = dict(action_kind='ARM_TRANSFER', control_mode='fleet_managed', workcell_id=catalog.workcell_id,
                      instance_id=catalog.instance_id, journal_id='journal-1', owner_session_id='session-1',
                      catalog_digest=catalog.digest, bindings_digest=installed.bindings.revision,
                      resource_policy_digest=installed.resource_policy_digest,
                      capability_revision=installed.capability_revision, config_revision=installed.config_revision)
    api = ActionApi(None)
    api.dispatch = lambda request, **_: {'version': 2, 'status': 200, 'capability': capability}
    path = tmp_path / catalog.instance_id / 'control.sock'
    path.parent.mkdir()
    server = UnixActionServer(api, path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    try:
        fleet = tool.fleet_installation(written, tmp_path)
    finally:
        server.stop()
    assert fleet.policy.digest == written['policy_digest'] and fleet.capabilities[0].journal_id == 'journal-1'
    with pytest.raises(ValueError, match='digest'):
        tool.fleet_installation({**written, 'policy_digest': 'f' * 64}, tmp_path)
