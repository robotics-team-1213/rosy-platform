"""Explicit SIM route/map/backend for the continuous charging HTTP scenario.

Only return navigation uses this ideal map-pose plant. Relative docking continues
through rendered pixels, the camera worker and the real observation HTTP path.
"""
import dataclasses
import math
from types import SimpleNamespace


def return_sim(*, svc, client, store, stations, return_http, clock, world, robot_id, navigation_candidate=None):
    from fleet.server.site_map_store import SiteMapStore
    from fleet.server.trip_runner import TripRunner
    from fleet.server.trip_ports import TripConfig
    from fleet.server.charge_trip_port import ChargeReturnTrip
    from fleet.routing.trip import PlanRequest, plan_trip
    from fleet.routing.execute import plan_body
    from core_common.protocol.station_charging import ChargeDecision
    from core_features.navigation.manager import NavGoalSpec
    from core_features.command.arbitration import Mode
    from test_trip_runner import Ports, BOTH, _free_map, _map
    from test_charge_trip_port import CAPS
    from test_station_return_handover import TrackedNavigation

    plant, backend = Ports(), TrackedNavigation(svc.nav)
    plant.caps[robot_id] = dataclasses.replace(BOTH, trip_lease=True, line_follow_authority=True)
    svc.nav.executor = backend
    svc.trip_lease._monotonic = clock
    plans = SiteMapStore(None, clock=clock)
    route_map = _free_map() if navigation_candidate is None else _map(
        ('A', 0, 0), ('B', 2, 0), ('C', 2, 1), edges=[
            ('ab', 'A', 'B', [[0, 0], [2, 0]], 'free'), ('bc', 'B', 'C', [[2, 0], [2, 1]], 'free')])
    plans.import_if_empty(route_map, source='SIM')  # Explicit surveyed SIM corridor includes the moved station.
    active = plans.active()
    arc = active[2].arcs['ab:fwd']
    plant.now = clock()
    plant.at(arc, world.pose[0])
    async def plan(session, target):
        route = plan_trip(active[2], PlanRequest(map_version=active[0], start_pose=world.pose,
            goal=(target.approach_pose.x, target.approach_pose.y, target.approach_pose.yaw)), plans.routing_config)
        plan_id = 'return-plan-'+session.session_id
        plans.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id='charge-policy',
            map_version=route.map_version, request={'to': target.approach_pose.model_dump()}, result={'plan': plan_body(route)})
        return plan_id
    async def goal(_, x, y, yaw, **kwargs):
        svc.modes.transition(Mode.NAVIGATION)
        svc.nav.goal(NavGoalSpec(x, y, yaw), correlation_id='SIM-return-goal')
        if navigation_candidate is None and abs(world.pose[0]-x) < .01:
            backend.done()
        return await plant.goal(robot_id, x, y, yaw)
    async def halt(_):
        if navigation_candidate is None:
            world.stop()
        else:
            navigation_candidate(0., 0.)
        return await plant.cancel_goal(robot_id)
    async def lease(_, body):
        return await client.trip_lease(body)
    async def release(_, lease_id):
        return await client.trip_lease_release(lease_id)
    plant.trip_lease, plant.trip_lease_release = lease, release
    runner = TripRunner(store=plans, routing_config=plans.routing_config, caps=plant.caps_for,
        poses=plant, junction=plant, goal=goal, cancel_goal=halt, clock=clock,
        config=TripConfig(), lease={'required': True, 'holder': 'station'})
    runner.lease._clock = clock
    runner.authority.enabled = True
    runner.lease.claimed = lambda _: next(iter(store.tasks.resource_claims(resource_kind='robot', resource_id=robot_id)), None)
    async def lost(view, detail):
        raise AssertionError(('SIM unexpected charge lease loss', view, detail))
    runner.lease.on_charge_lost = lost
    adapter = ChargeReturnTrip(runner=runner, plans=plans, store=store, stations=stations,
        robot_port=return_http, plan=plan, capabilities=lambda _: CAPS, principal_id='charge-policy',
        map_scope=lambda version, map_id: ('floor', 'map-1') if (version, map_id) == (active[0], active[1].map_id) else None,
        clock=clock, admit_return=lambda *_: ChargeDecision(decision='RETURN_REQUIRED', reason='SIM_BUDGET',
            profile_revision='SIM', capacity_revision=None))
    async def step(*, tick_runner=True):
        # Explicit ideal SIM navigation; continuous motion still crosses the final publisher.
        if svc.modes.mode is Mode.NAVIGATION and svc.nav.nav_state.value == 'NAVIGATING':
            x, y, yaw = world.pose
            goal_x = backend.spec.x
            if navigation_candidate is None:
                x = min(goal_x, x+.01)
                world.pose = (x, 0., 0.)
                world.command = (.2 if x < goal_x else 0., 0.)
                if x >= goal_x-.001:
                    world.stop()
                    backend.done()
            else:
                dx, dy = goal_x-x, backend.spec.y-y
                distance = math.hypot(dx, dy)
                final_error = math.remainder((backend.spec.yaw or 0.)-yaw, 2*math.pi)
                if distance <= .005 and abs(final_error) <= .01:
                    navigation_candidate(0., 0.)
                    backend.done()
                else:
                    direction = 1 if dx*math.cos(yaw)+dy*math.sin(yaw) >= 0 else -1
                    heading = math.atan2(dy, dx)+(math.pi if direction < 0 else 0.)
                    error = final_error if distance <= .005 else math.remainder(heading-yaw, 2*math.pi)
                    linear = direction*min(.2, 2*distance) if distance > .005 and abs(error) < .2 else 0.
                    navigation_candidate(linear, max(-.6, min(.6, 2*error)))
        plant.now = clock()
        plant.at(arc, world.pose[0])
        if tick_runner:
            await runner.tick()
    def use_runner(actual):
        nonlocal runner
        runner = actual
        runner._clock = clock  # Explicit SIM source clock; application constructs the actual owner.
        runner.lease._clock = clock
        runner.charge_goal_ready = adapter.ready_free_goal
        adapter.runner = runner
        result.runner = runner
    result = SimpleNamespace(adapter=adapter, runner=runner, step=step, backend=backend,
                             plant=plant, use_runner=use_runner)
    return result
