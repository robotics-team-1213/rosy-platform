"""Compose read-only observation providers without a second Console snapshot loop."""

import asyncio

from fleet.server.background_workers import control_unit_loop
from fleet.server.control_unit_collection import ControlUnitCollection, control_information_loop
from fleet.server.control_unit_information import LocalControlInformation
from fleet.server.control_unit_information_routes import install_control_information_routes


def install_control_information(app, config, *, tasks, console, map_snapshot,
                                authorize, require_viewer):
    local = LocalControlInformation(
        config, gather=lambda: app.state.fleet_gather(), tasks=tasks.store,
        map_snapshot=map_snapshot, clock=console._clock,
        sampled_at=lambda: app.state.fleet_gather.gathered_at,
        pending_stops=lambda: app.state.control_unit_stops.store.pending_count(),
    )
    collection = ControlUnitCollection(config, local, app.state.control_unit.peer)
    app.state.control_unit_information = collection
    install_control_information_routes(app, collection, authorize=authorize, require_viewer=require_viewer)


def start_control_unit_tasks(app):
    if app.state.control_unit is None:
        return []
    return [asyncio.create_task(control_unit_loop(app.state.control_unit)),
            asyncio.create_task(control_information_loop(app.state.control_unit_information))]
