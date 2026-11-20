"""Explicit SIM device/source adapters for one robot's continuous camera lifecycle.

Contact, isolation, rear space and energy are synthetic installed measurements.
They never replace JPEG relative perception, native outcomes or ledger receipts.
"""
import json

from fleet.server.task_service import FleetTaskService
from fleet.server.channel.execution.outcomes.reconcile import task_result
from fleet.server.charge_policy_admission import work_request_digest
from core_features.docking.station_motion import StationMotionFeed
from core_features.docking.station_departure import StationDepartureFeed, StationDepartureSample
from core_features.docking.station_departure_control import StationDepartureController
from test_station_departure_feed import configured
from core.bridge.cmd_vel import cmd_vel_cycle
from core.bridge import docking_mode
from core_features.command.manager import Twist


class StationCycleSim:
    def __init__(self, *, svc, world, clock, tasks, robot_id, station_x, signals):
        self.svc, self.world, self.clock = svc, world, clock
        self.robot_id, self.station_x, self.signals = robot_id, station_x, signals
        self.tasks = FleetTaskService(tasks, robot_ids={robot_id})
        tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()['generation'], actor_id='SIM')
        self.soc, self.work = 10., None
        self.sequence, self.still_since, self.last_motion = 0, None, None
        self.events = []
        self.wheels = []
        self.blocked_phases = set()
        self.dock_candidate = self.nav_candidate = (0., 0.)
        svc.docking.executor = self
        self.unsubscribe = svc.nav._events.subscribe(lambda event: self.events.append(event.model_dump(mode='json')))
        owner = svc.station_docking
        self.motion = StationMotionFeed(clock=clock, source_clock=clock, max_age_s=.25)
        owner.motion_feed = self.motion
        self.departure = StationDepartureFeed(profile=configured()[1].profile, clock=clock, source_clock=clock)
        owner.departure = StationDepartureController(owner, feed=self.departure)

    def drive(self, linear, angular):
        self.dock_candidate = (linear, angular)

    def stop(self):
        self.dock_candidate = (0., 0.)

    def navigation_candidate(self, linear, angular):
        self.nav_candidate = (linear, angular)

    def navigate_to(self, pose):
        self.world.navigate_to(pose)

    def cancel_navigation(self):
        self.nav_candidate = (0., 0.)

    def set_collision_exemption(self, enabled):
        self.world.set_collision_exemption(enabled)

    def travelled_m(self):
        return self.world.travelled_m()

    def reset_odometry_mark(self):
        self.world.reset_odometry_mark()

    def odometry_pose(self):
        return self.world.pose

    def apply_output(self, dt=.05):
        """Every plant step, including ARRIVED/IDLE, consumes only the final output."""
        command = self.svc.command
        command.set_nav_twist(Twist(*self.nav_candidate))
        command.set_docking_twist(Twist(*self.dock_candidate))

        def wheels(out):
            self.wheels.append((out.linear, out.angular))
            self.world.drive(out.linear, out.angular)
        phase = self.svc.station_docking.state
        candidate = self.nav_candidate if self.svc.modes.mode.value == 'NAVIGATION' else self.dock_candidate
        before = self.world.pose
        power_ready = self.svc.power.motion_ready
        block = phase not in self.blocked_phases and any(candidate)
        if block:
            self.svc.power.motion_ready = lambda: False  # One explicit SIM power-readiness interruption.
        try:
            cmd_vel_cycle(command, self.svc.power, wheels, self.svc.readiness,
                motion_ready=lambda: docking_mode.motion_ready(self.svc))
        finally:
            self.svc.power.motion_ready = power_ready
        self.world.step(dt)
        if block:
            assert self.wheels[-1] == (0., 0.) and self.world.pose == before
            self.blocked_phases.add(phase)

    def attach(self, ports, runtime):
        ports.work_handover = self.tasks.handover_completed_navigation
        runtime.finish_work = ports.finish_work
        self.tasks.charge_admission = runtime.work_admission

    def boundary(self):
        owner = self.svc.station_docking
        if owner.state == 'CHARGED_HOLD':
            return not self.signals['moving'] and self.world.command == (0., 0.)
        return (self.svc.modes.mode.value == 'IDLE' and self.still_since is not None
                and self.clock()-self.still_since >= owner.profile.still_s)

    def pulse(self):
        owner, at = self.svc.station_docking, self.clock()
        linear, angular = self.world.command
        if self.signals['moving']:
            linear = .02
        stamp = int(at*1e9)
        assert self.motion.observe(stamp_ns=stamp, source_now_ns=stamp, frame_id='odom',
            child_frame_id='base_link', odom_epoch='0', measured_linear_m_s=linear,
            measured_angular_rad_s=angular)
        self.svc.state.set_velocity(linear, angular)
        self.svc.state.set_odom_pose(*self.world.pose, source_stamp_ns=stamp)
        self.svc.localization.on_state(json.dumps(dict(status=dict(state='LOCALIZED', pose_frame='map'),
            pose=dict(zip(('x', 'y', 'yaw'), self.world.pose)), stamp=at)))  # Explicit ideal SIM localization.
        measured = self.motion.snapshot()
        if (self.svc.modes.mode.value != 'IDLE' or abs(linear) > owner.profile.linear_limit_m_s
                or abs(angular) > owner.profile.angular_limit_rad_s or measured is None
                or self.last_motion is not None and at-self.last_motion > owner.profile.sample_max_age_s):
            self.still_since = None
        elif self.still_since is None:
            self.still_since = measured['captured_at']
        self.last_motion = at
        if owner.session is None:
            return
        if owner.state in ('UNDOCKING', 'DEPARTURE_CHECK', 'WORK_AVAILABLE'):
            self.signals['contact'] = self.world.pose[0] > self.station_x-.04
        self.sequence += 1
        session = owner.session
        body = {key: getattr(session, key) for key in ('robot_id', 'station_id', 'session_id', 'attempt_id',
            'boot_id', 'battery_id', 'map_id', 'map_revision', 'pose_revision')}
        body.update(profile_revision='departure-1', source_id='local-departure', source_epoch='source-boot',
            sequence=self.sequence, odom_epoch='0', captured_at=at, valid_until=at+.2,
            motion_sample_at=at, space_sample_at=at, power_sample_at=at, current_sample_at=at,
            contact_sample_at=at, pose=dict(zip(('x', 'y', 'yaw'), self.world.pose)),
            measured_linear_m_s=linear, measured_angular_rad_s=angular,
            rear_clearance_m=.5, sweep_verified=True, output_enabled=not self.signals['normal'],
            charging=self.signals['contact'] and not self.signals['normal'],
            current_a=0. if self.signals['normal'] else .2, load_present=self.signals['contact'], faults=())
        assert self.departure.ingest(StationDepartureSample.model_validate(body))

    def budget_work(self):
        if self.work is None:
            return dict(work_task_id=None, work_request_digest=None)
        current = self.tasks.store.get_task(self.work['task_id'])
        return dict(work_task_id=current['task_id'], work_request_digest=work_request_digest(current))

    async def queue(self, cycle):
        self.work = await self.tasks.submit_navigation(robot_id=self.robot_id, x=.9, y=0., source='operator',
            actor_id='SIM', request_key=f'cycle-{cycle}')
        self.soc = 75.

    async def dispatch(self, console):
        async def send(attempt):
            goal = attempt['request']['goal']
            return await console.goal(self.robot_id, **goal, task_id=attempt['task_id'],
                attempt_id=attempt['attempt_id'], attempt_seq=attempt['attempt_seq'], lease_source='dispatch')
        result = await self.tasks.dispatch_next({self.robot_id}, dispatch=send)
        assert result is not None and result['status'] == 'ACCEPTED', result
        assert result['task_id'] == self.work['task_id']

    async def completed(self, client):
        while self.events:
            self.tasks.project_core_event(self.events.pop(0))
        task = self.tasks.store.get_task(self.work['task_id'])
        if task['status'] != 'COMPLETED':
            return False
        await task_result(self.tasks.store, client, task)
        current = self.tasks.store.get_task(task['task_id'])
        assert current['receipt']['safe_released'] is True
        assert not self.tasks.store.resource_claims(resource_kind='robot', resource_id=self.robot_id)
        return True
