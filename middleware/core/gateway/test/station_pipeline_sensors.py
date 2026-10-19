"""Explicit synthetic dock and motion readings for the camera SIM."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core_features.docking.agent import DockReachability, DockStatus
from core_features.docking.station_sensors import DockSample, StationSensorReader


@pytest.fixture
def pipeline_sources(monkeypatch):
    """This cross-domain test must also run alone, without sibling conftest collection."""
    root = Path(__file__).resolve().parents[4]
    for relative in ('operations/fleet', 'operations/fleet/test', 'operations/world/src',
                     'operations/decision/src', 'operations/site_execution/src', 'operations/overhead',
                     'operations/apps/games', 'operations/situation',
                     'middleware/core/services/test'):
        monkeypatch.syspath_prepend(str(root / relative))


def sensors(now, signals, world):
    def cached_contact():
        status = DockStatus(DockReachability.OK, dock_id='charger-1',
            load_present=signals['contact'], charging=signals['contact'] and not signals['normal'],
            load_sample_at=now[0], termination='NORMAL' if signals['normal'] else 'UNKNOWN',
            termination_source='charger' if signals['normal'] else 'unknown',
            termination_sample_at=now[0] if signals['normal'] else None,
            battery_id='pack-1' if signals['normal'] else None)
        return DockSample(status, now[0], now[0])
    cache = SimpleNamespace(start=lambda: None, close=lambda: None, snapshot=cached_contact)
    return StationSensorReader(clock=lambda: now[0], source_clock=lambda: now[0],
        poller_factory=lambda *args, **kwargs: cache,
        battery_health=lambda: dict(sample_age_s=0., filtered_voltage=8.25),
        motion_sample=lambda: dict(odom_epoch='0', captured_at=now[0],
            measured_linear_m_s=0.02 if signals['moving'] else world.command[0],
            measured_angular_rad_s=world.command[1]))
