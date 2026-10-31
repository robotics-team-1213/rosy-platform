"""D-927 C3: one simulation ARM_TRANSFER installation for the owner, Fleet and the observer/writer.

Order: the owner catalog and bindings (no policy needed) -> the Fleet policy over their digests -> the owner starts
with that policy digest -> Fleet completes TransferInstallation with the owner's live UDS capability.

  python3 tools/sim/transfer_installation.py write --out installation.json   # policy, digest, bases
  ROSY_ARM_TRANSFER_INSTALLATION=installation.json  (run_cell_owner.py reads it)
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'deploy/robot/omx/sim/transfer_installation.yaml'
ASSETS = ROOT / 'learning/envs/isaac/assets/open_manipulator_description'
for _part in ('contracts/foundation', 'middleware/devices/omx/adapter', 'integrations/robots/omx/src',
              'operations/processes/palletizing/src', 'operations/world/src', 'operations/fleet'):
    if str(ROOT / _part) not in sys.path:
        sys.path.append(str(ROOT / _part))


def load(path=SPEC):
    spec = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if spec.get('schema') != 'rosy.sim-transfer-installation/1':
        raise ValueError('not a sim transfer installation')
    return spec


def _job(spec):
    from rosy.processes.palletizing.cell import load_cell
    from rosy.processes.palletizing.compiler import compile_job
    from rosy.processes.palletizing.recipe import load_recipe
    recipe = load_recipe((ROOT / spec['recipe']).read_text(encoding='utf-8'))
    job = compile_job(recipe, load_cell((ROOT / spec['cell']).read_text(encoding='utf-8')), tol_m=0.001)
    source, target = job.steps[spec['source_step']], job.steps[spec['target_step']]
    if (source.kind, target.kind) != ('pick', 'place') or source.item != target.item:
        raise ValueError('source/target steps must be one pick and its place')
    return recipe, job, source, target


def bindings(spec):
    """The owner's catalog (robot_base frame) and object binding; same input, same digests."""
    from omx_adapter.contracts.transfer_motion import GraspGeometry
    from omx_adapter.kinematics import OmxKinematics, TopDownPose
    from omx_adapter.pose_plan import CellPlanningProfile
    from omx_adapter.transfer_object_bindings import TransferObjectBindings
    from omx_adapter.transfer_preflight import ArmTransferCatalog, TransferPose
    recipe, job, source, target = _job(spec)
    kin, profile = OmxKinematics.load(), CellPlanningProfile.load(ROOT / 'deploy/robot/omx/sim/cell_profile.yaml')
    home = TopDownPose(*_home(spec))
    poses = {name: TransferPose(TopDownPose(s.target.x, s.target.y, s.target.z, s.target.yaw), s.approach_z)
             for name, s in (('source', source), ('target', target))}
    catalog = ArmTransferCatalog(
        workcell_id=spec['workcell_id'], instance_id=spec['instance_id'], profile_revision=profile.revision,
        kinematics_revision=kin.revision, calibration_revision=spec['calibration_revision'],
        transform_revision=spec['transform_revision'], planning_scene_revision=kin.planning_scene_revision,
        home=home, carry_z=job.carry_z, poses=poses,
        geometries={source.item: GraspGeometry(recipe.box.width, recipe.box.grasp_depth, recipe.box.height, True)})
    return TransferObjectBindings(catalog, {spec['object']['ref']: source.item})


def _home(spec):
    from rosy.processes.palletizing.cell import load_cell
    home = load_cell((ROOT / spec['cell']).read_text(encoding='utf-8')).home
    return home.x, home.y, home.z, home.yaw


def object_pose(spec, step, height):
    """World pose of the box centre under a step's top-face TCP target (base = world, D-877 world)."""
    (x, y, z), w = _world(spec, (step.target.x, step.target.y, step.target.z - height / 2)), step.target.yaw
    base = spec['base']['orientation_xyzw']
    return (x, y, z), _qmul(base, (0.0, 0.0, math.sin(w / 2), math.cos(w / 2)))


def _qmul(a, b):
    (ax, ay, az, aw), (bx, by, bz, bw) = a, b
    return (aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw, aw*bw - ax*bx - ay*by - az*bz)


def _world(spec, point):
    qx, qy, qz, qw = spec['base']['orientation_xyzw']
    t = [2 * (qy * point[2] - qz * point[1]), 2 * (qz * point[0] - qx * point[2]), 2 * (qx * point[1] - qy * point[0])]
    rotated = (point[0] + qw * t[0] + qy * t[2] - qz * t[1], point[1] + qw * t[1] + qz * t[0] - qx * t[2],
               point[2] + qw * t[2] + qx * t[1] - qy * t[0])
    return tuple(r + p for r, p in zip(rotated, spec['base']['position_m']))


def zones(spec, recipe, source, target):
    """One box over each object position: arm links at rest must stay outside it."""
    from rosy.world.state.projections.physical_transfer import Bounds3
    hx, hy = spec['zone_half_m']
    out = []
    for step in (source, target):
        (x, y, z), _ = object_pose(spec, step, recipe.box.height)
        top = z + recipe.box.height / 2 + spec['zone_clearance_above_m']
        out.append(Bounds3((x - hx, y - hy, 0.0), (x + hx, y + hy, top)))
    return tuple(out)


def policy(spec, installed):
    """The Fleet policy over the owner catalog and bindings digests."""
    from fleet.server.evidence.physical_transfer_evidence import PhysicalTransferPolicy, TransferParticipant
    from rosy.world.state.projections.omx_geometry import load_omx_geometry
    from rosy.world.state.projections.physical_transfer import PhysicalPose
    recipe, _, source, target = _job(spec)
    urdf = (ASSETS / 'urdf/omx_f/omx_f.urdf').read_bytes()
    meshes = {n.attrib['filename']: (ASSETS / n.attrib['filename'].removeprefix(
        'package://open_manipulator_description/')).read_bytes() for n in ET.fromstring(urdf).findall('.//mesh')}
    workcell, instance = spec['workcell_id'], spec['instance_id']
    participant = TransferParticipant(
        workcell_id=workcell, instance_id=instance, arm_resource_id=f'{workcell}.{instance}',
        geometry=load_omx_geometry(urdf, meshes), calibration_revision=spec['calibration_revision'],
        transform_revision=spec['transform_revision'])
    pose = {name: PhysicalPose(*object_pose(spec, step, recipe.box.height))
            for name, step in (('source', source), ('target', target))}
    return PhysicalTransferPolicy(
        participants=(participant,), primary=(workcell, instance), zones=zones(spec, recipe, source, target),
        zone_resource_ids=(f'{workcell}.source', f'{workcell}.target'), object_resource_id=spec['object']['ref'],
        zone_margin_m=spec['zone_margin_m'], producer_id=spec['producer_id'],
        evaluator_revision=spec['evaluator_revision'], frame_id='world', catalog_digest=installed.catalog.digest,
        bindings_digest=installed.revision, object_ref=spec['object']['ref'], object_origin_id=spec['object']['body'],
        source_pose=pose['source'], target_pose=pose['target'],
        **{k: spec[k] for k in ('position_tolerance_m', 'orientation_tolerance_rad', 'max_linear_speed_m_s',
                                'max_angular_speed_rad_s', 'max_age_ns', 'min_separation_ns')})


def owner_installation(spec, policy_digest):
    """What run_cell_owner.py installs: the same bindings, bound to the Fleet policy digest."""
    from rosy.integrations.robots.omx.arm_transfer import ArmTransferInstallation
    return ArmTransferInstallation(bindings(spec), spec['capability_revision'], spec['config_revision'],
                                   policy_digest)


def owner_installation_from_environment():
    """None without ROSY_ARM_TRANSFER_INSTALLATION; otherwise the owner side, checked against the written file."""
    path = os.environ.get('ROSY_ARM_TRANSFER_INSTALLATION')
    if not path:
        return None
    written = json.loads(Path(path).read_text(encoding='utf-8'))
    installed = owner_installation(load(), written['policy_digest'])
    if (installed.bindings.catalog.digest, installed.bindings.revision) != (
            written['policy']['catalog_digest'], written['policy']['bindings_digest']):
        raise ValueError('the written installation was built from another catalog')
    return installed


def fleet_installation(written, socket_root):
    """Fleet's TransferInstallation: the written policy plus the running owner's own capability."""
    from fleet.server.evidence.physical_transfer_evidence import PhysicalTransferPolicy
    from fleet.server.local_action_transport import UnixLocalActionTransport
    from fleet.server.work.physical_transfer_store import TransferInstallation
    installed = PhysicalTransferPolicy.model_validate(written['policy'])
    if installed.digest != written['policy_digest']:
        raise ValueError('policy digest does not match the written policy')
    transport = UnixLocalActionTransport(socket_root)
    capabilities = tuple(transport.transfer_capability(p.instance_id, workcell_id=p.workcell_id)
                         for p in installed.participants)
    return TransferInstallation(policy=installed, source='source', target='target', capabilities=capabilities)


def document(spec):
    installed = policy(spec, bindings(spec))
    return {'schema': 'rosy.sim-transfer-installation-written/1', 'policy': installed.model_dump(mode='json'),
            'policy_digest': installed.digest, 'bases': {spec['instance_id']: spec['base']},
            'object': spec['object']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=('write',))
    parser.add_argument('--spec', type=Path, default=SPEC)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    written = document(load(args.spec))
    args.out.write_text(json.dumps(written, indent=1, sort_keys=True), encoding='utf-8')
    args.out.with_name(args.out.stem + '.bases.json').write_text(json.dumps(written['bases']), encoding='utf-8')
    print(written['policy_digest'])


if __name__ == '__main__':
    main()
