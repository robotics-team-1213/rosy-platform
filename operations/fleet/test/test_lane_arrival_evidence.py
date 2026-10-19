"""A stop receipt is not evidence that its physical destination was reached."""
import dataclasses
import math

import pytest

from test_trip_runner import _arc, _plan, _setup, _ticks, run


def accepted_stop():
    runner, store, ports = _setup()
    arc = _arc(store, 'east:fwd')
    _plan(store, ports, 'east:fwd', .5, 'SE')
    run(runner.start('p1', 'bob'))
    ports.at(arc, arc.length_m - .25)
    _ticks(runner, ports)
    assert runner.view('p1')['state'] == 'running'
    return runner, ports, arc


def test_executing_stop_does_not_end_the_trip_before_the_configured_arrival_distance():
    runner, ports, arc = accepted_stop()
    sent = len(ports.sent)
    _ticks(runner, ports)
    assert runner.view('p1')['state'] == 'running'
    assert runner._live['rosy_60'].open
    ports.core.see_junction()
    _ticks(runner, ports)
    assert runner.view('p1')['state'] == 'running'  # Even an actual hold is not spatial arrival.
    ports.at(arc, arc.length_m - .14)
    _ticks(runner, ports)
    assert runner.view('p1')['state'] == 'arrived'
    assert len(ports.sent) == sent


@pytest.mark.parametrize('offset', [(0., .2), (.2, 0.)])
def test_projection_past_the_endpoint_does_not_hide_physical_distance(offset):
    runner, ports, arc = accepted_stop()
    live = runner._live['rosy_60']
    x, y, yaw = arc.point_at(arc.length_m)
    along, lateral = offset
    ports.pose = dataclasses.replace(ports.pose,
        x=x + along * math.cos(yaw) - lateral * math.sin(yaw),
        y=y + along * math.sin(yaw) + lateral * math.cos(yaw))
    live.see(ports.pose)
    # The projection is at/past the endpoint; the actual pose is still .2m away.
    assert not runner._arrived(live, 0, -along, True, ports.pose)


def test_traffic_hold_back_keeps_its_existing_stop_destination(monkeypatch):
    runner, ports, arc = accepted_stop()
    live = runner._live['rosy_60']
    import fleet.server.trip_progress as progress
    monkeypatch.setattr(progress, 'hold_back_m', lambda *_: .2)
    ports.at(arc, arc.length_m - .3)
    live.see(ports.pose)
    assert runner._arrived(live, 0, .3, True, ports.pose)
