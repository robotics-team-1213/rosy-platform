"""Native boot receipts qualify the existing shared REST read and World projection."""
import asyncio
import importlib
import importlib.util

import pytest

from fleet.server.map_pose_service import MapPoseService
from test_map_pose_service import Wall, T0, state, row


def api():
    name = 'fleet.server.charge_world_pose'
    assert importlib.util.find_spec(name) is not None, 'native-scoped charge World source is missing'
    return importlib.import_module(name)


def fixture():
    module = api()
    wall, active, current = Wall(), ['floor', 'map-1'], {}
    class Robot:
        robot_id = 'r1'
        boot = 'boot-1'
        hook = None
        reads = 0
        owners = 0
        async def docking_status(self):
            self.owners += 1
            if self.hook: self.hook(self)
            return {'owner': {'boot_id': self.boot}}
        async def state(self):
            self.reads += 1
            wall.now += .05
            body = state(wall.now)
            body['map_id'] = 'floor'
            body['odom_pose']['epoch'] = 0
            return body
    robot = current['r1'] = Robot()
    async def gather(rid): return await current[rid].state()
    poses = MapPoseService(lambda: list(current), wall=wall, clock=lambda: wall.now-T0,
        map_id=lambda: active[0], gather_rest=gather, client_identity=lambda rid: current[rid])
    source = module.ChargeWorldPoseSource(robot_id='r1', poses=poses, clients=lambda: current,
        active_scope=lambda: tuple(active), clock=wall, monotonic=lambda: wall.now-T0+10., max_age_s=2.)
    def facts():
        return dict(robot_id='r1', boot_id='boot-1', odom_epoch='0', map_id='floor',
                    map_revision='map-1', captured_at=wall.now, valid_until=wall.now+2.)
    return source, poses, robot, current, wall, active, facts


async def localized(source, poses, wall, facts):
    for _ in range(3):
        await source.read(facts())
        poses.observe_sighting(row(wall.now) | {'map_id': 'floor'})
    sample = facts()
    proof = await source.read(sample)
    assert proof is not None
    return sample, proof


def test_actual_shared_state_and_original_camera_anchor_produce_bound_pose():
    async def run():
        source, poses, robot, _, wall, _, facts = fixture()
        sample, proof = await localized(source, poses, wall, facts)
        assert proof.boot_id == 'boot-1' and proof.odom_epoch == '0'
        assert proof.map_revision == 'map-1' and proof.odom_stamp <= wall.now
        assert proof.anchor_stamp <= proof.odom_stamp
        assert source.current(proof, sample)
        assert robot.reads == 4 and robot.owners == 8
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['boot', 'client', 'map_revision', 'epoch', 'expired'])
def test_changed_input_or_second_boot_receipt_retires_previous_proof(fault):
    async def run():
        source, poses, robot, current, wall, active, facts = fixture()
        original, proof = await localized(source, poses, wall, facts)
        sample = facts()
        if fault == 'epoch': sample['odom_epoch'] = '1'
        elif fault == 'expired': sample['valid_until'] = wall.now
        else:
            def change(owner):
                if owner.owners % 2 == 0:
                    if fault == 'boot': owner.boot = 'boot-2'
                    elif fault == 'client': current['r1'] = object()
                    else: active[1] = 'map-2'
            robot.hook = change
        with pytest.raises(ValueError, match='CHARGE_WORLD_POSE_UNAVAILABLE'):
            await source.read(sample)
        assert not source.current(proof, original)
    asyncio.run(run())


def test_original_proof_expires_and_cannot_be_forged():
    async def run():
        source, poses, _, _, wall, _, facts = fixture()
        sample, proof = await localized(source, poses, wall, facts)
        assert not source.current(object(), sample)
        assert source.current(proof, sample)
        wall.now += 2.01
        assert not source.current(proof, sample)
    asyncio.run(run())


def test_new_revision_requires_new_odometry_scope_and_camera_anchor():
    async def run():
        source, poses, _, _, wall, active, facts = fixture()
        original, old = await localized(source, poses, wall, facts)
        wall.now += .1
        active[1] = 'map-2'
        current_facts = lambda: facts() | {'map_revision': 'map-2'}
        assert await source.read(current_facts()) is None
        assert not source.current(old, original)
        assert await source.read(current_facts()) is None
        sample, proof = await localized(source, poses, wall, current_facts)
        assert proof is not None and source.current(proof, sample)
        assert proof.map_revision == 'map-2' and proof.scope is not old.scope
        assert proof.anchor_stamp > old.anchor_stamp
    asyncio.run(run())


def test_final_guard_cannot_rebind_issued_pose_to_other_facts():
    async def run():
        source, poses, _, _, wall, _, facts = fixture()
        sample, proof = await localized(source, poses, wall, facts)
        assert not source.current(proof, sample | {'boot_id': 'other'})
        assert not source.current(proof, sample)
    asyncio.run(run())


def test_shared_receipt_is_bound_to_actual_transport_and_immutable_original_body():
    async def run():
        _, poses, robot, _, _, _, _ = fixture()
        raw = await poses.state('r1')
        receipt = await poses.state_with_source('r1')
        assert receipt.client is robot and receipt.number == 1 and robot.reads == 1
        original = receipt.state['odom_pose']['x']
        raw['odom_pose']['x'] = 99.
        receipt.state['odom_pose']['x'] = 55.
        assert receipt.state['odom_pose']['x'] == original
    asyncio.run(run())


def test_bound_scope_still_shares_reads_and_actual_sender_cannot_be_replaced_by_gather():
    async def run():
        _, poses, robot, _, wall, _, _ = fixture()
        poses.begin_source_scope('r1', boot_id='boot-1', odom_epoch='0', client=robot)
        async def wrong_gather(_):
            raise AssertionError('source receipt must use the captured client itself')
        poses._gather_rest = wrong_gather
        one = await poses.state('r1')
        receipt = await poses.state_with_source('r1')
        two = await poses.state('r1')
        assert one is two and receipt.client is robot and robot.reads == 1
        assert poses.survey_odom('r1') is None  # A transport receipt is not qualified ingestion.
    asyncio.run(run())


def test_reader_reconstruction_requires_a_new_camera_anchor():
    async def run():
        source, poses, _, current, wall, active, facts = fixture()
        sample, proof = await localized(source, poses, wall, facts)
        fresh = api().ChargeWorldPoseSource(robot_id='r1', poses=poses, clients=lambda: current,
            active_scope=lambda: tuple(active), clock=wall, monotonic=lambda: wall.now-T0+10., max_age_s=2.)
        assert await fresh.read(facts()) is None
        assert not source.current(proof, sample)
    asyncio.run(run())


def test_unchanged_camera_anchor_keeps_first_monotonic_deadline_across_new_odom():
    async def run():
        source, poses, _, _, wall, _, facts = fixture()
        await localized(source, poses, wall, facts)
        mono = [wall.now-T0+10.]
        source.monotonic = lambda: mono[0]
        mono[0] += .8
        assert await source.read(facts()) is not None
        mono[0] += 1.3
        with pytest.raises(ValueError, match='CHARGE_WORLD_POSE_UNAVAILABLE'):
            await source.read(facts())
    asyncio.run(run())


@pytest.mark.parametrize('change', ['client', 'map_revision'])
def test_observed_final_guard_contradiction_cannot_revive_by_restoring_old_value(change):
    async def run():
        source, poses, robot, current, wall, active, facts = fixture()
        sample, proof = await localized(source, poses, wall, facts)
        if change == 'client': current['r1'] = object()
        else: active[1] = 'other-revision'
        assert not source.current(proof, sample)
        current['r1'], active[1] = robot, 'map-1'
        assert not source.current(proof, sample)
        assert await source.read(facts()) is None
    asyncio.run(run())


def test_repeated_facts_keep_original_monotonic_deadline_with_independent_clocks():
    async def run():
        source, poses, _, _, wall, _, facts = fixture()
        await localized(source, poses, wall, facts)
        sample = facts()
        sample['valid_until'] = sample['captured_at']+.2
        assert await source.read(sample) is not None
        mono = [10.39]
        source.monotonic = lambda: mono[0]
        assert await source.read(sample) is not None
        mono[0] = 10.41
        assert wall.now < sample['valid_until']  # UTC still permits it; original mono lease does not.
        with pytest.raises(ValueError, match='CHARGE_WORLD_POSE_UNAVAILABLE'):
            await source.read(sample)
    asyncio.run(run())


def test_older_facts_cannot_regain_a_lease_after_a_newer_original_capture():
    async def run():
        source, poses, _, _, wall, _, facts = fixture()
        await localized(source, poses, wall, facts)
        first = facts()
        assert await source.read(first) is not None
        second = facts()
        assert second['captured_at'] > first['captured_at']
        assert await source.read(second) is not None
        assert wall.now < first['valid_until']
        with pytest.raises(ValueError, match='CHARGE_WORLD_POSE_UNAVAILABLE'):
            await source.read(first)
    asyncio.run(run())


def test_first_state_predating_identity_boundary_waits_without_repeated_scope_reset():
    async def run():
        source, poses, robot, _, wall, _, facts = fixture()
        original = robot.state
        async def one_old_sample():
            if robot.reads:
                return await original()
            robot.reads += 1
            body = state(wall.now-.01)
            body['map_id'], body['odom_pose']['epoch'] = 'floor', 0
            return body
        robot.state = one_old_sample
        assert await source.read(facts()) is None
        generation = poses._source_scopes.generation('r1')
        wall.now += .1
        assert await source.read(facts()) is None
        assert poses._source_scopes.generation('r1') == generation
        await localized(source, poses, wall, facts)
    asyncio.run(run())
