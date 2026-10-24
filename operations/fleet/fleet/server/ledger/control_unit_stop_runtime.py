"""Bind the typed request journal to this instance's existing device stop owner."""

from fleet.server.control_stop_store import ControlStopStore
from fleet.server.control_unit_stop_routes import install_control_stop_routes
from fleet.server.control_unit_stops import ControlUnitStops
from fleet.server.task_dispatch_routes import execute_local_fleet_stop


def validate_control_stop_owners(config, *, console, configured_omx, signals):
    resources = config.topology.unit(config.unit_id).resources
    robots = {resource[6:] for resource in resources if resource.startswith("robot:")}
    if robots != set(console.robot_ids):
        raise ValueError("CONTROL_UNIT_LOCAL_ROBOT_OWNER_MISMATCH")
    if not {"workcell:" + workcell for workcell in configured_omx} <= resources:
        raise ValueError("CONTROL_UNIT_LOCAL_OMX_OWNER_MISMATCH")
    signal_ids = tuple(signals.snapshot()) if signals is not None else ()
    if not {"signal:" + signal for signal in signal_ids} <= resources:
        raise ValueError("CONTROL_UNIT_LOCAL_SIGNAL_OWNER_MISMATCH")
    return signal_ids


def install_control_stops(app, config, *, tasks, console, configured_omx, stop_transport,
                          signal_ids, authorize, require_viewer, require_named_operator):
    journal = ControlStopStore(tasks.store, unit_id=config.unit_id,
                               config_revision=config.topology.revision)
    journal.recover()

    async def stop(control, actor):
        return await execute_local_fleet_stop(
            console=console, task_service=tasks, configured_omx=configured_omx,
            stop_transport=stop_transport, stop_control=control, actor_id=actor)

    service = ControlUnitStops(config, journal, app.state.control_unit.peer, stop, signal_ids=signal_ids)
    app.state.control_unit_stops = service
    install_control_stop_routes(app, service, authorize=authorize, require_viewer=require_viewer,
                                require_named_operator=require_named_operator)
