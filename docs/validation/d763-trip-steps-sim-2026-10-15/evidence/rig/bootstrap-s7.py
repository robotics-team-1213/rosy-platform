"""Private SIM bootstrap: actual native GZ odom, original receipt, actual /clock.

No command publisher, camera sighting, pin, epoch reset or fabricated stamp.
The frozen product port validates trust and supplies only execution consumers.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path('/home/ai/rosy-test/d763-sim')
SOURCE = ROOT / 'source-s7'  # D-763 slice 7 branch: Fleet code only (CORE built from main)
OUT = Path(os.environ['D763_OUT'])
for rel in reversed(['operations/fleet', 'contracts/foundation', 'contracts/learning/src',
                     'contracts/motion/src', 'contracts/skill/src', 'operations/world/src',
                     'operations/execution/src', 'operations/decision/src', 'tools/sim']):
    sys.path.insert(0, str(SOURCE / rel))
sys.path.insert(0, str(ROOT / 'overlay-fleet'))
import rclpy
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from rclpy.qos import QoSProfile, ReliabilityPolicy
from native_gazebo_map_pose import NativeGazeboBinding, NativeRobotBinding
from native_gazebo_map_pose import NativeGazeboSample, NativeGazeboMapPosePort
import fleet.server.app as app_module

manifest = json.loads((OUT / 'native-pose-binding.json').read_text())
manifest['map_from_world'] = tuple(manifest['map_from_world'])
manifest['robots'] = tuple(NativeRobotBinding(**robot) for robot in manifest['robots'])
binding = NativeGazeboBinding(**manifest)
receipt = json.loads((OUT / 'source-receipt.json').read_text())
selection = json.loads((OUT / 'map-selection.json').read_text())
assert selection == dict(map_variant='.',
                         world_rel='middleware/perception/map/map_v2_fleet/worlds/map_v2_fleet_real.world',
                         graph_rel='middleware/perception/map/map_v2_fleet/lane_graph.yaml',
                         scorer_profile='original_real',source_revision=receipt['source_revision'])
assert binding.source_revision == receipt['source_revision']
assert str(binding.domain_id) == os.environ['ROS_DOMAIN_ID']
assert binding.partition == os.environ['GZ_PARTITION']
for name, rel in [('world_sha256', 'middleware/perception/map/map_v2_fleet/worlds/map_v2_fleet_real.world'),
                  ('graph_sha256', 'middleware/perception/map/map_v2_fleet/lane_graph.yaml'),
                  ('urdf_sha256', 'middleware/devices/pinky/description/urdf/rosy_gz.urdf.xacro')]:
    assert hashlib.sha256((SOURCE / rel).read_bytes()).hexdigest() == getattr(binding, name), rel


def canonical(stamp):
    assert type(stamp.sec) is int and stamp.sec >= 0
    assert type(stamp.nanosec) is int and 0 <= stamp.nanosec < 1_000_000_000
    return stamp.sec * 1_000_000_000 + stamp.nanosec


class Producer:
    def __init__(self, port):
        self.port, self.clock, self.pending = port, None, {}
        self.stop = threading.Event()
        self.event_lock = threading.Lock()
        self.node = rclpy.create_node('native_map_pose_m1')
        self.trace = (OUT / 'native-pose-events.jsonl').open('w', buffering=1)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.subs = [self.node.create_subscription(Clock, '/clock', self.on_clock, qos)]
        for robot in binding.robots:
            self.subs.append(self.node.create_subscription(Odometry, '/' + robot.robot_id + '/odom',
                            lambda msg, robot=robot: self.on_native(robot, msg), qos))
        self.thread = threading.Thread(target=self.spin, name='native-map-pose', daemon=True)

    def event(self, kind, **fields):
        packet = json.dumps(dict(kind=kind, at_wall=time.time(), at_monotonic=time.monotonic(), **fields)) + '\n'
        with self.event_lock:
            if not self.trace.closed:
                self.trace.write(packet)

    def identity(self, topic, expected):
        actual = [(p.node_name, p.node_namespace) for p in self.node.get_publishers_info_by_topic(topic)]
        if actual != [expected]:
            self.event('publisher_rejected', topic=topic, actual=actual, expected=expected)
            for robot in binding.robots:
                self.port._fail(robot.robot_id, 'native_publisher_identity')
            return False
        return True

    def on_clock(self, msg):
        wall, mono = time.time(), time.monotonic()
        if not self.identity('/clock', ('bridge_rosy_01', '/')):
            return
        try:
            stamp = canonical(msg.clock)
        except (AssertionError, ValueError):
            self.port.observe_clock(-1)
            self.event('clock_invalid', received_wall=wall, received_monotonic=mono)
            return
        accepted = self.port.observe_clock(stamp)
        self.event('clock', stamp_ns=stamp, accepted=accepted, received_wall=wall, received_monotonic=mono)
        if not accepted:
            return
        self.clock = stamp
        for robot_id in tuple(self.pending):
            self.join(robot_id)

    def on_native(self, robot, msg):
        # Capture receipts before parsing, graph introspection or buffering.
        wall, mono = time.time(), time.monotonic()
        if not self.identity('/' + robot.robot_id + '/odom', ('bridge_' + robot.robot_id, '/')):
            return
        try:
            stamp = canonical(msg.header.stamp)
            q = msg.pose.pose.orientation
            assert all(math.isfinite(v) for v in (q.x, q.y, q.z, q.w))
            assert abs(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w - 1.) <= .001
            p = msg.pose.pose.position
            pose = (p.x, p.y, math.atan2(2*(q.w*q.z + q.x*q.y), 1-2*(q.y*q.y + q.z*q.z)))
            sample = NativeGazeboSample(binding, robot.robot_id, robot.model,
                                       msg.header.frame_id, stamp, pose)
        except (AssertionError, ValueError):
            self.port._fail(robot.robot_id, 'native_message_invalid')
            self.event('native_invalid', robot_id=robot.robot_id, received_wall=wall, received_monotonic=mono)
            return
        self.event('native_received', robot_id=robot.robot_id, stamp_ns=stamp,
                   frame_id=sample.frame_id, pose=pose, received_wall=wall, received_monotonic=mono)
        if robot.robot_id in self.pending:
            # Losing an unjoined frame is explicit failure, never refreshing it.
            self.port._fail(robot.robot_id, 'unjoined_native_replaced')
            self.event('native_rejected', robot_id=robot.robot_id, reason='unjoined_native_replaced')
            return
        self.pending[robot.robot_id] = (sample, wall, mono)
        self.join(robot.robot_id)

    def join(self, robot_id):
        sample, wall, mono = self.pending[robot_id]
        elapsed = max(time.time()-wall, time.monotonic()-mono)
        if self.clock is None or sample.stamp_ns > self.clock:
            if elapsed <= self.port.config.max_pair_s:
                return
            self.port._fail(robot_id, 'native_join_timeout')
            accepted = False
        else:
            accepted = self.port.observe(sample, clock_stamp_ns=self.clock,
                                         received_wall=wall, received_monotonic=mono)
        del self.pending[robot_id]
        self.event('native_join', robot_id=robot_id, stamp_ns=sample.stamp_ns,
                   clock_stamp_ns=self.clock, accepted=accepted, received_wall=wall,
                   received_monotonic=mono, diagnostic=self.port.diagnostics(robot_id))

    def spin(self):
        try:
            while not self.stop.is_set():
                rclpy.spin_once(self.node, timeout_sec=.01)
                for robot_id in tuple(self.pending):
                    self.join(robot_id)
        except Exception as error:
            for robot in binding.robots:
                self.port._fail(robot.robot_id, 'native_collector_exception')
            self.event('collector_exception', error=repr(error))

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3.)
        assert not self.thread.is_alive()
        self.node.destroy_node()
        with self.event_lock:
            self.trace.close()
        rclpy.shutdown()


# ---- D-763 SIM check harness shim (NOT product code) ------------------------------------------
# main has no HTTP entry for TripAdmission.hold_job / start(job_id) / release_job (slice 7 wires
# them to the Step ledger) and no on_job_lost wiring. This shim calls those product methods
# in-process so the SIM can exercise slice 6; on_job_lost here only records what the product passed.
def _install_d763_shim(app):
    from fastapi import Header, HTTPException
    from fleet.server.trip_ports import TripError
    lost = []
    want = os.environ['D763_HARNESS_TOKEN']
    def auth(token):
        if token != 'Bearer ' + want:
            raise HTTPException(401, 'harness token')
    def runner():
        r = app.state.trip_runner
        if r.lease.on_job_lost is None:
            async def on_job_lost(view, detail):
                lost.append(dict(at=time.time(), view={k: view.get(k) for k in ('robot_id', 'job_id', 'trip_id')}, detail=detail))
            r.lease.on_job_lost = on_job_lost
        return r
    def refused(exc):
        return {'refused': True, 'status': exc.status, 'code': exc.code, 'detail': exc.detail}
    @app.post('/api/_d763_harness/hold')
    async def hold(body: dict, authorization: str = Header(default='')):
        auth(authorization); r = runner()
        caps = await app.state.console._client(body['robot_id']).capabilities()
        try:
            return {'lease': await r.hold_job(body['robot_id'], body['job_id'], 'd763-sim-operator', caps)}
        except TripError as exc:
            return refused(exc)
    @app.post('/api/_d763_harness/start')
    async def start(body: dict, authorization: str = Header(default='')):
        auth(authorization); r = runner()
        try:
            return await r.start(body['plan_id'], 'd763-sim-operator', job_id=body.get('job_id'))
        except TripError as exc:
            return refused(exc)
    @app.post('/api/_d763_harness/release')
    async def release(body: dict, authorization: str = Header(default='')):
        auth(authorization); r = runner()
        try:
            r.release_job(body['robot_id'], body['job_id'])
            return {'released': True, 'job_of': r.lease.job_of(body['robot_id'])}
        except TripError as exc:
            return refused(exc)
    @app.get('/api/_d763_harness/state')
    async def state(authorization: str = Header(default='')):
        auth(authorization); r = runner()
        return {'jobs': {rid: j.view for rid, j in r.lease.jobs.items()}, 'lost': lost,
                'job_of': {rid: r.lease.job_of(rid) for rid in ('rosy_01', 'rosy_02')}}


original_create = app_module.create_app


def create_bound_app(console, **kwargs):
    assert kwargs.get('map_pose_port') is None
    rclpy.init()
    async def gather(robot_id):
        state = await console._client(robot_id).state()
        producer.event('core_snapshot', robot_id=robot_id, state=state)
        return state
    port = NativeGazeboMapPosePort(binding, gather_core=gather)
    producer = Producer(port)
    kwargs.update(map_pose_port=port, simulation_pose_binding=asdict(binding), deployment_profile='simulation')
    app = original_create(console, **kwargs)
    # slice 7: no harness shim, the product route POST /api/fleet/trip-jobs drives the job
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        producer.thread.start()
        async def refresh_both():
            # Actual REST reads at 2Hz; refresh coalesces with execution consumers.
            # Never replace cached UTC stamps or revive a failed port.
            while True:
                tick = time.monotonic()
                results = await asyncio.gather(*(port.refresh(robot.robot_id) for robot in binding.robots),
                                               return_exceptions=True)
                for robot, result in zip(binding.robots, results):
                    producer.event('core_refresh', robot_id=robot.robot_id,
                                   error=type(result).__name__ if isinstance(result, Exception) else None,
                                   diagnostic=port.diagnostics(robot.robot_id))
                await asyncio.sleep(max(0., .5-(time.monotonic()-tick)))
        task = None
        try:
            async with original_lifespan(app):
                task = asyncio.create_task(refresh_both())
                try:
                    yield
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        finally:
            # The product port shields coalesced actual REST tasks. Stop the app
            # consumers first, then drain those tasks before closing their trace.
            try:
                all_pending = set(port._refreshing.values())
                pending = all_pending
                initial_pending = len(pending)
                if pending:
                    _, pending = await asyncio.wait(pending, timeout=3.)
                for future in pending:
                    future.cancel()
                if pending:
                    _, pending = await asyncio.wait(pending, timeout=1.)
                errors = []
                for future in all_pending:
                    if future.done() and not future.cancelled():
                        error = future.exception()
                        if error is not None:
                            errors.append(type(error).__name__)
                producer.event('core_pending_shutdown', initial_pending=initial_pending,
                               unfinished=len(pending), errors=errors)
                if pending:
                    raise RuntimeError('Actual CORE snapshot tasks did not close within shutdown budget')
            finally:
                producer.close()
    app.router.lifespan_context = lifespan
    return app


app_module.create_app = create_bound_app
# SIM-only site map: the west road's drawn outside corners as D-507 bend places (vertex, radius
# 0.15 m as in docs/validation/lane-west-bend-candidate-2026-10-09). The lane graph file is unchanged.
import fleet.site_map as _site_map
_from_lane_graph = _site_map.from_lane_graph
_BENDS = [dict(id=i, name=i, kind='bend', x=x, y=y, yaw=math.radians(a), exit_yaw=math.radians(b), radius_m=0.15)
          for i, x, y, a, b in (
    ('B_W1', -0.6934, -0.5090, -116.58, 180.0), ('B_W2', -1.2691, -0.5090, 180.0, 90.0),
    ('B_W3', -1.2689, 0.5094, 90.0, 0.0), ('B_W4', -0.6914, 0.5085, 0.0, -63.63),
    ('B_E1', -0.0619, 0.5085, 69.61, 0.29), ('B_E2', 0.3228, 0.5104, 0.29, -89.03),
    ('B_E4', -0.0625, -0.5091, 180.0, 110.27))]
_BENDS.append(dict(id='LAP_END', name='lap end', kind='stop', x=-0.5762, y=0.2759, yaw=2.0568282561349895))
def _with_bends(*args, **kwargs):
    base = _from_lane_graph(*args, **kwargs).model_dump(by_alias=True)
    # One-way west road in the lap direction (NW -> SW), as the demo loop map: a two-way lane is a
    # one-robot zone, and a repeat trip may not hold at a place inside a zone.
    for edge in base['edges']:
        if edge['id'] == 'west':
            edge.update({'from': edge['to'], 'to': edge['from'], 'direction': 'one_way',
                         'polyline': edge['polyline'][::-1]})
    base['turn_bans'] = [ban for ban in base.get('turn_bans', []) if 'west' not in (ban.get('from_edge'), ban.get('to_edge'))]
    return _site_map.SiteMap.model_validate({**base, 'places': [*base['places'], *_BENDS]})
_site_map.from_lane_graph = _with_bends
from fleet.cli import main
main(sys.argv[1:])
