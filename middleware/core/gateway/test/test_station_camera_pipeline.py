"""Software SIM: rendered image -> camera worker -> Fleet -> CORE -> parking/seating.

The plant truth is used to render pixels and assess error, never as a camera pose.
Synthetic contact/BMS and ideal optics do not establish hardware acceptance.
"""
import asyncio
import math
import secrets
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.bridge import docking_mode
from core_common.protocol.station_charging import ChargeSessionStatus, Pose2D, StationPoseRecord
from test_station_docking_api import station_api


SIM_WAIT_S = 30.


async def _sim_call(function, *args, **kwargs):
    # SIM time controls permits; host ASGI/journal scheduling gets its own bounded test budget.
    return await asyncio.wait_for(function(*args, **kwargs), timeout=SIM_WAIT_S)


@pytest.fixture
def pipeline_sources(monkeypatch):
    """This cross-domain test must also run alone, without sibling conftest collection."""
    root = Path(__file__).resolve().parents[4]
    for relative in ('operations/fleet', 'operations/fleet/test', 'operations/world/src',
                     'operations/decision/src', 'operations/site_execution/src', 'operations/overhead',
                     'operations/apps/games', 'operations/situation',
                     'middleware/core/services/test'):
        monkeypatch.syspath_prepend(str(root / relative))


# lifespan, shutdown_UNDOCKING and continuous (~100-140 s each) run from test_station_camera_pipeline_{lifespan,
# continuous}.py: xdist --dist loadfile gives one file one worker, and this file alone was 511 of a 576 s run.
@pytest.mark.parametrize('full_return', [False, True, 'relocation_abort', 'composed',
                                      'motion_busy', 'shutdown_RETURNING', 'shutdown_CHARGING'])
def test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop(station_api, tmp_path,
                                                                                   pipeline_sources, full_return, monkeypatch):
    import cv2
    import httpx
    import numpy as np
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.station_ingress import StationIngress, StationSource
    from fleet.server.station_service import StationService
    from fleet.server.station_store import StationStore
    from fleet.server.charge_service import ChargeService
    from fleet.server.charge_robot_http import ChargeRobotHttp
    from fleet.server.station_return_http import StationReturnHttp
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient
    from core_features.docking.agent import DockReachability, DockStatus
    from core_features.docking.station_sensors import DockSample, StationSensorReader
    from rosy_vision.detect import generate_marker_image
    from rosy_vision.publish import SightingPublisher
    from rosy_vision.station_observation import StationCameraCalibration
    from rosy_vision.station_worker import create_station_worker
    from core_common.protocol.station_charging import ChargeDecision
    from test_charge_store import store
    from test_docking_parking_manager import World

    core, svc, now, auth, binding, _ = station_api
    shutdown_phase = (full_return.removeprefix('shutdown_')
                      if isinstance(full_return, str) and full_return.startswith('shutdown_') else None)
    continuous = shutdown_phase is not None or full_return in (
        'continuous', 'relocation_abort', 'composed', 'lifespan', 'motion_busy')
    composed = shutdown_phase is not None or full_return in ('composed', 'lifespan', 'motion_busy')
    lifespan = shutdown_phase is not None or full_return in ('lifespan', 'motion_busy')
    owner = svc.station_docking
    robot_id = svc.state.snapshot().robot_id
    station_x = 1.1 if full_return else 0.
    scene = SimpleNamespace(station_x=station_x)
    world = World((.1, 0., 0.) if full_return else (-0.10, 0.015, 0.04))
    if full_return:
        binding['target']['pose']['x'] = station_x
        binding['target']['approach_pose'] = dict(x=1., y=0., yaw=0.)
    svc.docking.executor = world
    svc.state._clock = svc.state._monotonic = lambda: now[0]
    binding['session']['robot_id'] = binding['observation_scope']['robot_id'] = robot_id
    binding['observation_scope']['odom_epoch'] = '0'
    # The full return must outlive its initial lease using distinct SIM global observations.
    binding['target']['valid_until'] = 102. if full_return else 160.
    original_scope = owner.local_scope
    def local_scope():
        return original_scope() | dict(robot_id=robot_id, odom_epoch='0',
            mode=svc.modes.mode.value if full_return else 'IDLE')
    owner.local_scope = owner.local_scope_nowait = local_scope
    signals = dict(contact=False, moving=False, normal=False)
    def cached_contact():
        status = DockStatus(DockReachability.OK, dock_id='charger-1',
            load_present=signals['contact'], charging=signals['contact'] and not signals['normal'],
            load_sample_at=now[0], termination='NORMAL' if signals['normal'] else 'UNKNOWN',
            termination_source='charger' if signals['normal'] else 'unknown',
            termination_sample_at=now[0] if signals['normal'] else None,
            battery_id='pack-1' if signals['normal'] else None)
        return DockSample(status, now[0], now[0])
    cache = SimpleNamespace(start=lambda: None, close=lambda: None, snapshot=cached_contact)
    owner.sensors = StationSensorReader(clock=lambda: now[0], source_clock=lambda: now[0],
        poller_factory=lambda *args, **kwargs: cache,
        battery_health=lambda: dict(sample_age_s=0., filtered_voltage=8.25),
        motion_sample=lambda: dict(odom_epoch='0', captured_at=now[0],
            measured_linear_m_s=0.02 if signals['moving'] else world.command[0],
            measured_angular_rad_s=world.command[1]))
    svc.state.set_odom_pose(*world.pose, source_stamp_ns=int(now[0]*1e9))
    if not full_return:
        bound = core.put('/api/v1/docking/station-target', headers=auth['fleet-a'], json=binding)
        assert bound.status_code == 200, bound.text
    charges, tasks = store(tmp_path)
    cycles = None
    if continuous:
        from station_cycle_sim import StationCycleSim
        cycles = StationCycleSim(svc=svc, world=world, clock=lambda: now[0], tasks=tasks,
            robot_id=robot_id, station_x=station_x, signals=signals)
    if not full_return:
        charges.reserve(ChargeSessionStatus.model_validate(binding['session']))
    registry = StationStore(tmp_path/'site.sqlite')
    registry.propose(StationPoseRecord.model_validate(binding['target'] | dict(status='CANDIDATE')))
    registry.confirm('charger-1', expected_revision=1)  # Explicit SIM installation, not relocation evidence.
    stations = StationService(registry, clock=lambda: now[0], map_scope=lambda: ('floor', 'map-1'),
        trusted_sources={'station-camera': ('camera-boot', 'mount-1'),
                         'global': ('global-boot', 'global-cal')},
        robot_scope=lambda _: (binding['expected_boot_id'], next((s.session_id for s in charges.list()
            if s.state != 'WORK_AVAILABLE'), 'charge-1')),
        approach_validator=lambda _: True, position_tolerance_m=0.03, heading_tolerance_rad=0.05,
        max_uncertainty_m=0.01, max_uncertainty_rad=0.02, consistency_samples=3)
    source_token = secrets.token_urlsafe(32)
    source = StationSource(source_id='station-camera', token=source_token, station_id='charger-1',
        robot_ids=(robot_id,), map_id='floor', map_revision='map-1', source_epoch='camera-boot',
        calibration_revision='mount-1', max_age_s=0.25, max_uncertainty_m=0.01, max_uncertainty_rad=0.02)
    global_token = secrets.token_urlsafe(32)
    global_source = StationSource(source_id='global', token=global_token, station_id='charger-1',
        robot_ids=(robot_id,), map_id='floor', map_revision='map-1', source_epoch='global-boot',
        calibration_revision='global-cal', max_age_s=2., max_uncertainty_m=.01, max_uncertainty_rad=.02)
    calibration = StationCameraCalibration(station_id='charger-1', source_id='station-camera',
        source_epoch='camera-boot', revision='mount-1', marker_id=7, marker_side_m=0.1,
        marker_mount=Pose2D(x=0., y=0., yaw=math.pi/2),
        image_to_station=(0.001, 0., -0.3, 0., -0.001, 0.3, 0., 0., 1.),
        plane='robot_marker', lens_rectified=True, approved=True, uncertainty_m=0.002, uncertainty_rad=0.005)
    frame = SimpleNamespace(header=SimpleNamespace(seq=0), captured_at=now[0], received_at=now[0], jpeg=b'')
    marker = generate_marker_image(7, 100)
    station_marker = generate_marker_image(33, 100)
    global_anchors = tuple(dict(marker_id=40+i, corners=((x, y), (x+49, y), (x+49, y+49), (x, y+49)))
                           for i, (x, y) in enumerate(((5, 5), (545, 5), (545, 545), (5, 545))))
    def render_global():
        # Independent fixed camera/map; station carries this marker and its local docking camera.
        canvas = np.full((600, 600), 255, dtype=np.uint8)
        for anchor in global_anchors:
            x, y = anchor['corners'][0]
            canvas[y:y+50, x:x+50] = generate_marker_image(anchor['marker_id'], 50)
        centre = round((scene.station_x-.8)*1000)
        canvas[250:350, centre-50:centre+50] = station_marker
        ok, data = cv2.imencode('.jpg', canvas)
        assert ok
        return data.tobytes()
    def render(visible=True):
        canvas = np.full((600, 600), 255, dtype=np.uint8)
        if visible:
            x, y, yaw = world.pose
            cx, cy = round(300+(x-scene.station_x)*1000), round(300-y*1000)
            if 50 <= cx <= 550 and 50 <= cy <= 550:
                canvas[cy-50:cy+50, cx-50:cx+50] = marker
                canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((cx, cy), math.degrees(yaw), 1.),
                                        (600, 600), borderValue=255)
        ok, encoded = cv2.imencode('.jpg', canvas)
        assert ok
        return encoded.tobytes()

    async def scenario():
        robot_token = auth['fleet-a']['Authorization'].removeprefix('Bearer ')
        endpoint = RobotEndpoint(robot_id, 'http://core', robot_token)
        async with httpx.AsyncClient(base_url='http://core', transport=httpx.ASGITransport(app=core.app)) as http:
            robot = HttpRobotClient(endpoint, http=http)
            ret = StationReturnHttp(clients=lambda: {robot_id: robot}, store=charges, stations=stations,
                clock=lambda: now[0], permit_ttl_s=1.)
            async def snapshot(_):
                sample = dict(robot_id=robot_id, boot_id=binding['expected_boot_id'], battery_id='pack-1',
                    captured_at=now[0], valid_until=now[0]+.2, mode=svc.modes.mode.value,
                    safety_latched=False, map_id='floor', map_revision='map-1',
                    safe_work_boundary=cycles.boundary() if cycles else True,
                    dock_state=svc.docking.state.value)  # Explicit SIM source readiness, no inferred health.
                if full_return:
                    from test_charge_policy import battery
                    sample.update(battery_energy=battery(captured_at=now[0], valid_until=now[0]+.2,
                        soc_percent=cycles.soc if cycles else 10.).model_dump(), charge_budget=dict(robot_id=robot_id,
                        boot_id=binding['expected_boot_id'], station_id='charger-1', map_id='floor',
                        map_revision='map-1', pose_revision=registry.get('charger-1').pose_revision,
                        profile_revision='profile-1',
                        source_id='SIM-route-budget', source_epoch='SIM-budget-boot', cost_revision='SIM-cost-1',
                        captured_at=now[0], valid_until=now[0]+.2, work_wh=4., return_wh=2., dock_wh=.5,
                        reserve_wh=1., work_duration_s=100., return_duration_s=50.,
                        work_task_id=None, work_request_digest=None))
                    if cycles:
                        sample['charge_budget'].update(cycles.budget_work())
                return sample
            async def observation_scope(session, *_):
                from core_common.protocol.station_charging import StationObservation
                if full_return and owner.session is not None and owner.session.session_id == session.session_id:
                    body = await ingress.observation_scope('Bearer '+source_token, robot_id)
                    return StationObservation.model_validate(body['scope'])
                # Explicit SIM permission bootstrap for an unbound new session, not an observation.
                return StationObservation.model_validate(binding['observation_scope'] | dict(
                    session_id=session.session_id, pose_revision=session.pose_revision,
                    captured_at=now[0], valid_until=now[0]+.2))
            returns = None
            if full_return:
                from station_return_sim import return_sim
                returns = return_sim(svc=svc, client=robot, store=charges, stations=stations,
                    return_http=ret, clock=lambda: now[0], world=world, robot_id=robot_id,
                    navigation_candidate=cycles.navigation_candidate if cycles else None)
                if not cycles:
                    owner.motion_feed = SimpleNamespace(snapshot=lambda: dict(odom_epoch='0', captured_at=now[0],
                        valid_until=now[0]+.25, measured_linear_m_s=world.command[0],
                        measured_angular_rad_s=world.command[1]), clear=lambda: None)
            ports = ChargeRobotHttp(clients=lambda: {robot_id: robot}, store=charges, stations=stations,
                clock=lambda: now[0], returns=returns.adapter if returns else None, return_http=ret,
                snapshot=snapshot, observation_scope=observation_scope)
            failures = []
            def trace_failure(label, call):
                async def traced(*args, **kwargs):
                    try:
                        return await call(*args, **kwargs)
                    except Exception:
                        import traceback
                        if len(failures) < 16:
                            failures.append(f'{label} at SIM {now[0]}\n'+traceback.format_exc())
                        print('STATION_ASYNC_FAILURE', failures[-1])
                        try:
                            if label == 'work_goal':
                                print('STATION_WORK_FAILURE', runtime.work_admission(robot_id),
                                    runtime.reason, runtime._work_snapshot, returns.runner.open_trips())
                            if returns and args and hasattr(args[0], 'operation_id'):
                                print('STATION_TRIP_FAILURE', returns.runner.view(args[0].operation_id))
                        except Exception as diagnostic_error:
                            print('STATION_TRIP_DIAGNOSTIC_UNAVAILABLE', repr(diagnostic_error))
                        raise
                return traced
            ports.read_operation = trace_failure('read_operation', ports.read_operation)
            ports.read_station = trace_failure('read_station', ports.read_station)
            original_live = ret._live
            def traced_live(session, target, body, **kwargs):
                try:
                    return original_live(session, target, body, **kwargs)
                except Exception:
                    failures.append(repr(('return readback', body.model_dump(), 'expected', target.model_dump())))
                    raise
            ret._live = traced_live
            readback_reports = []
            if lifespan:
                from station_readback_probe import install_readback_probe
                readback_reports = install_readback_probe(owner, cycles.motion, lambda: now[0], monkeypatch)
            contended_readbacks, return_submissions = [], []
            if full_return == 'motion_busy':
                original_readback = owner.readback
                def contended_readback():
                    # Occupy the actual feed lock inside the synchronous CORE read.
                    # Its nonblocking snapshot must fail closed, without an async lock hold.
                    with cycles.motion._lock:
                        body = original_readback()
                    contended_readbacks.append(body)
                    return body
                owner.readback = contended_readback
            original_start = ports.start_return
            async def traced_start(*args, **kwargs):
                return_submissions.append(args[0].session_id)
                try:
                    return await original_start(*args, **kwargs)
                except Exception as exc:
                    failures.append(repr(exc))
                    raise
            ports.start_return = traced_start
            original_bind = ports.bind_target
            async def traced_bind(*args):
                try:
                    return await original_bind(*args)
                except Exception as exc:
                    failures.append(repr(exc))
                    raise
            ports.bind_target = traced_bind
            original_departure = ports.advance_departure
            async def traced_departure(*args, **kwargs):
                try:
                    return await original_departure(*args, **kwargs)
                except Exception as exc:
                    import traceback
                    failures.append(traceback.format_exc())
                    raise
            ports.advance_departure = traced_departure
            from itertools import count
            ids = iter(value for index in count(1) for value in (f'charge-{index}', f'attempt-{index}'))
            monitor = ChargeService(charges, stations=stations, clock=lambda: now[0],
                policy_enabled=lambda: True, ports=ports, id_factory=lambda: next(ids),
                admit_return=lambda *_: ChargeDecision(decision='WORK_ALLOWED', reason='SIM_BUDGET',
                    profile_revision='sim-profile', capacity_revision=None))
            monitor.motion.checked = trace_failure('checked', monitor.motion.checked)
            monitor.motion.call = trace_failure('motion_call', _sim_call)
            if lifespan:
                from station_timing_probe import install_timing_probe
                timing = install_timing_probe(owner=owner, navigation=svc.nav, motion=monitor.motion, ports=ports, tasks=tasks,
                    registry=registry, app=core.app, clock=lambda: now[0], monkeypatch=monkeypatch)
            ingress = StationIngress(stations=stations, sessions=charges, sources=[source, global_source],
                clients=lambda: {robot_id: robot}, clock=lambda: now[0])
            if full_return:
                from fleet.server.charge_policy_admission import MeasuredChargePolicyAdmission
                from fleet.server.charge_runtime import ChargeRuntime
                from test_charge_policy import profile
                policy = MeasuredChargePolicyAdmission(profiles={robot_id: profile()}, clock=lambda: now[0],
                    measured_sources={robot_id: ('fuel_gauge', 'capacity-3')},
                    budget_source=('SIM-route-budget', 'SIM-budget-boot', 'SIM-cost-1'), max_age_s=.2)
                monitor.admit_return = policy
                runtime = ChargeRuntime(monitor, robot_id=robot_id, station_id='charger-1',
                    admission=policy, monotonic=lambda: now[0], period_s=.05)
                if cycles and not composed:
                    cycles.attach(ports, runtime)
                if cycles:
                    for _ in range(10):  # Actual distinct installed SIM odometry samples at initial rest.
                        now[0] += .05
                        cycles.pulse()
                if not composed:
                    first = await runtime.tick()
                    assert first.state == 'RETURNING', (first.reason, owner.reason, failures)
                    assert runtime.decision.reason == 'LOW_SOC_RETURN'
            tick_finished, tick_generation, runtime_tasks = asyncio.Condition(), [0], set()
            initial_core_tick = asyncio.Event()
            async def wait_runtime():
                async with tick_finished:
                    previous = tick_generation[0]
                    await asyncio.wait_for(tick_finished.wait_for(lambda: tick_generation[0] > previous), SIM_WAIT_S)
            if lifespan:
                original_tick = runtime.tick
                async def observed_tick():
                    runtime_tasks.add(asyncio.current_task())
                    await initial_core_tick.wait()
                    result = await original_tick()
                    async with tick_finished:
                        tick_generation[0] += 1
                        tick_finished.notify_all()
                    return result
                runtime.tick = observed_tick
            async def advance():
                if lifespan:
                    await wait_runtime()
                    return charges.get('charge-1')
                return await runtime.tick() if full_return else await monitor.advance('charge-1')
            console = FleetConsole([endpoint], [robot], clock=lambda: now[0])
            goal_clock = asyncio.Lock()
            work_admitting, clock_boundary = asyncio.Event(), asyncio.Event()
            original_goal = console.goal
            async def observed_goal(*args, **kwargs):
                if kwargs.get('task_id') is None or kwargs.get('lease_source') == 'trip':
                    return await original_goal(*args, **kwargs)
                async with goal_clock:
                    entered = now[0]
                    work_admitting.set()
                    try:
                        if lifespan and not clock_boundary.is_set():
                            await clock_boundary.wait()  # Force the first send to overlap a requested SIM step.
                        assert now[0] == entered, 'SIM clock advanced during ordinary goal admission'
                        result = await original_goal(*args, **kwargs)
                        assert now[0] == entered, 'SIM clock advanced during ordinary goal admission'
                        return result
                    finally:
                        work_admitting.clear()
            console.goal = trace_failure('work_goal', observed_goal)
            def build_runtime(context):
                assert context.plans is returns.adapter.plans
                returns.use_runner(context.runner)
                context.runner._call = trace_failure('trip_call', context.runner._call)
                context.runner._step_free = trace_failure('trip_free', context.runner._step_free)
                ports.clients = ports.return_http.clients = ingress.clients = context.clients
                return runtime
            app_options = dict(site_maps=returns.adapter.plans, trip_caps_port=returns.plant.caps_for,
                map_pose_port=returns.plant, lane_junction=returns.plant, traffic_authority=True,
                trip_lease={'required': True}, charge_runtime_factory=build_runtime) if composed else {}
            fleet = create_app(console, console_token=secrets.token_urlsafe(32), station_ingress=ingress,
                task_service=cycles.tasks if cycles else None, **app_options)
            original_refusal = console.trip_refusal
            def traced_refusal(robot_ids):
                refusal = original_refusal(robot_ids)
                if refusal and robot_id in console._goal_busy:
                    print('STATION_ADMISSION_REFUSAL', now[0], runtime.work_admission(robot_id),
                        runtime._work_snapshot, returns.runner.robot_busy(robot_id),
                        returns.runner.lease.jobs.get(robot_id), runtime._next_evaluation)
                return refusal
            console.trip_refusal = traced_refusal
            handover_checks = []
            if composed:
                assert runtime is fleet.state.charge_runtime
                assert returns.adapter.runner is fleet.state.trip_runner
                assert ports.work_handover.__self__.tasks is cycles.tasks
                assert ports.work_handover.__self__.console is console
                original_handover = ports.work_handover
                async def observed_handover(*args, **kwargs):
                    before = fleet.state.trip_runner._engaged(robot_id)
                    result = await original_handover(*args, **kwargs)
                    if result:
                        handover_checks.append((before, fleet.state.trip_runner._engaged(robot_id)))
                    return result
                ports.work_handover = observed_handover
                if not lifespan:
                    first = await runtime.tick()
                    assert first.state == 'RETURNING', (first.reason, owner.reason, failures)
            @asynccontextmanager
            async def application_lifetime():
                async with fleet.router.lifespan_context(fleet):
                    yield
                assert runtime._closed
                assert len(runtime_tasks) == 1 and all(task.done() for task in runtime_tasks)
            async with (
                AsyncExitStack() as lifetime,
                SightingPublisher('http://fleet', source_token, transport=httpx.ASGITransport(app=fleet)) as publisher,
                SightingPublisher('http://fleet', global_token, transport=httpx.ASGITransport(app=fleet)) as global_publisher,
            ):
                worker = create_station_worker(calibration=calibration, robot_id=robot_id,
                    ingest=SimpleNamespace(latest_frame=lambda _: frame), rectify=lambda data: data,
                    publisher=publisher, clock=lambda: now[0], max_age_s=0.25)
                global_worker = None
                global_frame = SimpleNamespace(header=SimpleNamespace(seq=0), captured_at=now[0],
                    received_at=now[0], jpeg=b'')
                if cycles:
                    from rosy_vision.station_map_worker import StationMapCalibration, create_station_map_worker
                    fixed = StationMapCalibration(station_id='charger-1', map_id='floor', map_revision='map-1',
                        source_id='global', source_epoch='global-boot', revision='global-cal', pose_revision_hint=1,
                        marker_id=33, marker_side_m=.1, marker_mount=Pose2D(x=0., y=0., yaw=math.pi/2),
                        image_to_map=(.001, 0., .8, 0., -.001, .3, 0., 0., 1.), plane='station_marker',
                        lens_rectified=True, approved=True, fixed_map_anchor=True,
                        image_anchors=global_anchors, max_anchor_error_px=.5,
                        uncertainty_m=.002, uncertainty_rad=.005, approach_offset_m=.1)
                    global_worker = create_station_map_worker(calibration=fixed,
                        ingest=SimpleNamespace(latest_frame=lambda _: global_frame), rectify=lambda data: data,
                        publisher=global_publisher, clock=lambda: now[0], max_age_s=2.)
                if lifespan:
                    await lifetime.enter_async_context(application_lifetime())
                next_global = [now[0]]
                async def step(*, visible=True, server_running=True):
                    if work_admitting.is_set():
                        clock_boundary.set()
                    async with goal_clock:
                        pass  # SIM time advances between ordinary goal admissions.
                    if cycles:
                        cycles.apply_output()
                    elif svc.modes.mode.value != 'NAVIGATION':
                        world.step(0.05)
                    now[0] += 0.05
                    if full_return and now[0] >= next_global[0]:
                        if global_worker:
                            global_frame.header.seq += 1
                            global_frame.captured_at = global_frame.received_at = now[0]
                            global_frame.jpeg = render_global()
                            await global_worker.process_latest()
                        else:
                            # Isolated legacy variant: explicit SIM global source.
                            candidate = StationPoseRecord.model_validate(binding['target'] | dict(
                                status='CANDIDATE', captured_at=now[0], valid_until=now[0]+2.))
                            assert stations.observe(candidate).pose_revision == 1
                        next_global[0] = now[0]+.5
                    if returns:
                        await returns.step(tick_runner=not lifespan)
                    svc.state.set_odom_pose(*world.pose, source_stamp_ns=int(now[0]*1e9))
                    if cycles:
                        cycles.pulse()
                    frame.header.seq += 1
                    frame.captured_at = frame.received_at = now[0]
                    frame.jpeg = render(visible)
                    await worker.process_latest()
                    docking_mode.tick(svc, pytest.fail, station=owner)
                    if lifespan and not initial_core_tick.is_set():
                        # Exercise a CORE timer before the async worker's initial binding.
                        # Startup must preserve the real, already-pulsed motion sample.
                        assert owner.session is None and owner.state == 'UNBOUND'
                        assert cycles.motion.snapshot() is not None
                        initial_core_tick.set()
                    if full_return and server_running:
                        if lifespan:
                            await wait_runtime()
                        else:
                            await runtime.tick()
                async def shutdown_and_restart(phase):
                    from station_restart_sim import restart_held_station
                    before = charges.get('charge-1')
                    assert before.state == phase
                    intent = charges.operation_intent(before.session_id)
                    if cycles.work is None:
                        await cycles.queue(99)
                    await lifetime.aclose()
                    held = charges.get(before.session_id)
                    assert held.state == 'HOLD'
                    assert (held.session_id, held.attempt_id, held.operation_id) == (
                        before.session_id, before.attempt_id, before.operation_id)
                    after_intent = charges.operation_intent(before.session_id)
                    assert all(after_intent[key] == intent[key] for key in (
                        'session_id', 'kind', 'correlation_id', 'operation_id'))
                    held_pose = world.pose
                    async def pump():
                        await step(server_running=False)
                        assert world.pose == held_pose and cycles.wheels[-1] == (0., 0.)
                    await pump()
                    await restart_held_station(core=core, endpoint=endpoint, original=monitor,
                        ingress=ingress, pump=pump, work_id=cycles.work['task_id'])
                    assert return_submissions == ['charge-1']
                    cycles.unsubscribe()
                await step()
                if full_return == 'motion_busy':
                    current = charges.get('charge-1')
                    assert current.state == 'HOLD' and current.reason == 'CHARGE_OPERATION_SUBMISSION_UNKNOWN'
                    assert contended_readbacks and all(not body.binding_valid and body.ack is None
                        for body in contended_readbacks)
                    assert any('CHARGE_RETURN_CORE_SCOPE_CHANGED' in failure for failure in failures)
                    assert any(step.get('motion_lock_acquired') is False
                        for report in readback_reports for step in report['steps'])
                    held_pose = world.pose
                    for _ in range(12):
                        await step()
                        assert world.pose == held_pose and cycles.wheels[-1] == (0., 0.)
                    assert return_submissions == ['charge-1'] and returns.backend.current is None
                    assert not returns.adapter._tasks and len(charges.list()) == 1
                    assert charges.get('charge-1').state == 'HOLD'
                    assert tasks.resource_claims(resource_kind='robot', resource_id=robot_id)
                    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
                    cycles.unsubscribe()
                    return
                if full_return == 'relocation_abort':
                    await asyncio.wait_for(returns.adapter._tasks['charge-1'], 1.)
                    for _ in range(30):
                        await step()
                        if world.pose[0] > .15:
                            break
                    assert owner.state == 'RETURNING' and world.command[0] > 0.
                    scene.station_x = cycles.station_x = 1.3
                    next_global[0] = now[0]
                    await step()
                    assert registry.get('charger-1').status == 'INVALID'
                    for _ in range(12):
                        await step()
                        if charges.get('charge-1').state == 'HOLD':
                            break
                    assert charges.get('charge-1').state == 'HOLD'
                    await step()  # Exact stop becomes a candidate, then the final publisher applies it.
                    stopped = world.pose
                    for _ in range(32):
                        await step()
                        assert world.pose == stopped and cycles.wheels[-1] == (0., 0.)
                    assert registry.get('charger-1').pose_revision == 2
                    assert charges.get('charge-1').state == 'HOLD' and len(charges.list()) == 1
                    assert tasks.resource_claims(resource_kind='robot', resource_id=robot_id)
                    assert tasks.resource_claims(resource_kind='station', resource_id='charger-1')
                    cycles.unsubscribe()
                    return
                if full_return:
                    started = await advance()
                    assert started.state == 'RETURNING', (started.reason, owner.reason, failures)
                    await asyncio.wait_for(returns.adapter._tasks['charge-1'], 1.)
                    for _ in range(400):
                        await step()
                        current = await advance()
                        assert current.state != 'HOLD', (current.reason, owner.reason, world.pose, failures)
                        if shutdown_phase == 'RETURNING' and current.state == 'RETURNING' and world.command[0] > 0.:
                            await shutdown_and_restart('RETURNING')
                            return
                        if current.state == 'DOCKING':
                            break
                    assert shutdown_phase != 'RETURNING', 'return shutdown must execute during forward motion'
                    assert current.state == 'DOCKING'
                    assert charges.return_context('charge-1')['phase'] == 'FINISHED'
                    assert returns.backend.canceled == 0
                    run_id = current.operation_id
                else:
                    assert owner.feed.relative_pose() is not None
                    # This variant isolates camera docking; the other executes a real TripRunner return.
                    charges.transition('charge-1', expected_state='RETURN_RESERVED', next_state='RETURNING',
                        attempt_id='attempt-1', now=now[0], reason='SIM_RETURN_HANDOVER')
                    session = charges.transition('charge-1', expected_state='RETURNING', next_state='DOCKING',
                        attempt_id='attempt-1', now=now[0], reason='SIM_DOCK_SUBMITTED',
                        intent_kind='dock', correlation_id='image-sim-1')
                    run_id = await ports.start_dock(session, stations.store.get('charger-1'), correlation_id='image-sim-1')
                    charges.acknowledge_operation('charge-1', correlation_id='image-sim-1', operation_id=run_id, now=now[0])
                for _ in range(600):
                    await step()
                    if owner.state != 'DOCKING':
                        break
                assert owner.state == 'SEATING', (owner.state, owner.reason, world.pose)
                assert math.hypot(world.pose[0]-station_x, world.pose[1]) <= 0.020
                assert abs(world.pose[2]) <= math.radians(5)
                assert stations.accept_ack((await robot.station_target()).ack)
                assert (await advance()).state == 'CHARGE_CONFIRMING'
                assert charges.get('charge-1').operation_id == run_id
                for _ in range(20):
                    await step()
                assert not owner.readback().seating_verified
                signals.update(contact=True, moving=True)
                for _ in range(20):
                    await step()
                assert not owner.readback().seating_verified
                signals['moving'] = False
                for _ in range(30):
                    await step()
                live = owner.readback()
                if lifespan and not (live.seating_verified and live.charging_verified):
                    timing('seating_assertion')
                assert live.seating_verified and live.charging_verified, (
                    live.state, live.reason, world.pose, world.command, owner.feed.relative_pose(),
                    owner.sensors._proof_at, owner.seating._since, owner._seated_until)
                assert not live.completion_verified
                assert (await advance()).state == 'CHARGING'
                if shutdown_phase == 'CHARGING':
                    await shutdown_and_restart('CHARGING')
                    return
                if full_return:
                    original_charge_deadline = owner.target.valid_until
                    for _ in range(60):  # Three SIM seconds cross the two-second global pose lease.
                        await step()
                        assert charges.get('charge-1').state == 'CHARGING'
                    assert now[0] > original_charge_deadline
                signals['normal'] = True
                await step()
                live = owner.readback()
                assert live.completion_verified and live.state == 'CHARGED_HOLD'
                assert not live.charging_verified and world.command == (0., 0.)
                assert (await advance()).state == 'CHARGED_HOLD'
                assert (await advance()).state == 'CHARGED_HOLD'
                if full_return:
                    assert now[0] > binding['target']['valid_until']
                    assert owner.target.valid_until > now[0] and owner.target.pose_revision == 1
                assert tasks.resource_claims(resource_kind='robot', resource_id=robot_id)
                if cycles:
                    completed_sessions = []
                    for number in range(1, 4):
                        sid = f'charge-{number}'
                        assert charges.get(sid).state == 'CHARGED_HOLD'
                        await cycles.queue(number)
                        for _ in range(240):
                            await step()
                            current = charges.get(sid)
                            if current.state == 'HOLD':
                                pytest.fail(str((current.reason, owner.reason, world.pose))+'\n'+'\n'.join(failures))
                            if shutdown_phase == 'UNDOCKING' and current.state == 'UNDOCKING' and world.command[0] < 0.:
                                await shutdown_and_restart('UNDOCKING')
                                return
                            if current.state == 'WORK_AVAILABLE':
                                break
                        assert shutdown_phase != 'UNDOCKING', 'departure shutdown must execute during reverse motion'
                        assert current.state == 'WORK_AVAILABLE', (current.state, current.reason, owner.reason)
                        assert not tasks.resource_claims(resource_kind='station', resource_id='charger-1')
                        assert charges.departure_context(sid)['receipt']['session_id'] == sid
                        if not lifespan:
                            await cycles.dispatch(console)
                        for _ in range(100):
                            await step()
                            if lifespan:
                                work = tasks.get_task(cycles.work['task_id'])
                                complete = work['status'] == 'COMPLETED' and work['receipt'].get('safe_released') is True
                                if complete:
                                    assert not tasks.resource_claims(resource_kind='robot', resource_id=robot_id)
                            else:
                                complete = await cycles.completed(robot)
                            if complete:
                                break
                        else:
                            raise AssertionError(('ordinary work did not complete',
                                tasks.get_task(cycles.work['task_id']), world.pose,
                                svc.nav.nav_state.value, returns.backend.current, returns.runner.open_trips(),
                                [(task.get_name(), [(stack_frame.f_code.co_name, stack_frame.f_lineno)
                                    for stack_frame in task.get_stack(limit=2)])
                                 for task in list(asyncio.all_tasks())[:16]], failures))
                        assert math.hypot(world.pose[0]-.9, world.pose[1]) <= .02, (
                            'ordinary work receipt before physical SIM arrival', number, world.pose)
                        assert abs(math.remainder(world.pose[2], 2*math.pi)) <= math.radians(5)
                        assert svc.modes.mode.value == 'NAVIGATION', 'native result itself must not fake IDLE'
                        completed_sessions.append(sid)
                        if number == 3:
                            break
                        if number == 1:
                            # Move the empty station and its camera; keep robot pose and all owners unchanged.
                            before_robot = world.pose
                            scene.station_x = cycles.station_x = 1.3
                            next_global[0] = now[0]
                            await step()
                            assert world.pose == before_robot
                            assert registry.get('charger-1').status == 'INVALID'
                            assert stations.ready_for_return(robot_id, 'charger-1') is None
                            for _ in range(30):
                                await step()
                                relocated = registry.get('charger-1')
                                if relocated.status == 'VALID':
                                    break
                            assert relocated.status == 'VALID' and relocated.pose_revision == 2
                            assert relocated.pose.x == pytest.approx(1.3, abs=.003)
                            with pytest.raises(ValueError, match='STATION_POSITION_NOT_VERIFIED'):
                                await monitor.request_return(robot_id, 'charger-1', pose_revision=1,
                                    reason='SIM_STALE_POSITION_MUST_NOT_DISPATCH')
                            assert charges.get('charge-2') is None
                        cycles.soc = 10.
                        signals.update(contact=False, normal=False)
                        next_sid = f'charge-{number+1}'
                        for _ in range(500):
                            await step()
                            current = charges.get(next_sid)
                            if current is not None:
                                assert current.state != 'HOLD', (current.reason, owner.reason, world.pose, failures)
                                if current.state == 'DOCKING':
                                    break
                        assert current is not None and current.state == 'DOCKING', (
                            runtime.reason, owner.reason, svc.modes.mode.value, world.pose)
                        assert current.pose_revision == owner.session.pose_revision == 2
                        assert owner.target.pose.x == pytest.approx(1.3, abs=.003)
                        for _ in range(600):
                            await step()
                            if owner.state == 'SEATING':
                                break
                        assert owner.state == 'SEATING', (owner.state, owner.reason, world.pose)
                        assert math.hypot(world.pose[0]-scene.station_x, world.pose[1]) <= .020
                        signals['contact'] = True
                        for _ in range(40):
                            await step()
                        assert charges.get(next_sid).state == 'CHARGING', (
                            charges.get(next_sid).reason, owner.reason)
                        signals['normal'] = True
                        for _ in range(10):
                            await step()
                        assert charges.get(next_sid).state == 'CHARGED_HOLD'
                    assert completed_sessions == ['charge-1', 'charge-2', 'charge-3']
                    assert len(charges.list()) == 3 and returns.backend.canceled == 0
                    assert any(linear > 0 for linear, _ in cycles.wheels)
                    assert any(linear < 0 for linear, _ in cycles.wheels)
                    assert {'RETURNING', 'DOCKING', 'UNDOCKING', 'WORK_AVAILABLE'} <= cycles.blocked_phases
                    assert all(row.state == 'WORK_AVAILABLE' for row in charges.list())
                    if lifespan:
                        assert len(handover_checks) == 2 and all(after is None for _, after in handover_checks)
                    elif composed:
                        assert handover_checks == [('goal', None), ('goal', None)]
                    cycles.unsubscribe()
                    return
                await step(visible=False)
                live = owner.readback()
                assert not live.seating_verified and not live.charging_verified and not live.completion_verified
                assert (await advance()).state == 'HOLD'
                assert tasks.resource_claims(resource_kind='robot', resource_id=robot_id)
    asyncio.run(scenario())
