"""Charge-only pre-dispatch fence, independent of route/Decision geometry."""


async def ready_free_goal(runner, live):
    job = runner.lease.jobs.get(live.view['robot_id'])
    if job is None or job.view.get('owner_kind') != 'charge_session':
        return True
    if runner.charge_goal_ready is None:
        raise ValueError('CHARGE_RETURN_NAVIGATION_PORT_REQUIRED')
    ready = await runner._call(runner.charge_goal_ready(live.view['robot_id'], job))
    if runner.lease.jobs.get(live.view['robot_id']) is not job:
        raise ValueError('CHARGE_RETURN_LEASE_LOST')
    return ready is True
