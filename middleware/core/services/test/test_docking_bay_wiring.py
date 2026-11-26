"""CORE's LiDAR body scan reaches the bay phases through the manager (2026-11-19 review: observation.bay_body_scan
called two DockingManager methods that did not exist; the AttributeError was swallowed, so no scan ever arrived and
every bay turn failed closed with "no fresh body scan")."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from core.bridge.observation import bay_body_scan

from test_docking_bay import a_bay


def _services(manager):
    cfg = SimpleNamespace(body_front_x_m=0.10, body_rear_x_m=-0.07, body_half_width_m=0.0566,
                          body_rotation_radius_m=0.12, body_lidar_x_m=0.0, lidar_forward_deg=0.0,
                          obstacle_body_margin_m=0.0, lidar_self_mask=())
    return SimpleNamespace(docking=manager, line_follow=SimpleNamespace(config=cfg))


def _open_scan(count=360, rng=3.0):
    return {"ranges": [rng] * count, "angle_min": -math.pi, "angle_increment": 2.0 * math.pi / count,
            "range_min": 0.05, "range_max": 10.0}


def test_body_scan_reaches_the_bay_phases_through_the_manager():
    p = a_bay()
    p.manager.dock()
    assert p.manager.body_scan_rear_overhang() == pytest.approx(0.135)
    bay_body_scan(_services(p.manager), _open_scan(), received_at=p.clock.now)
    body = p.manager._bay_phases._body
    assert body is not None and body[3] == pytest.approx(p.clock.now)


def test_no_body_scan_is_taken_when_no_bay_dock_is_active():
    p = a_bay()
    assert p.manager.body_scan_rear_overhang() is None
    bay_body_scan(_services(p.manager), _open_scan(), received_at=p.clock.now)
    assert p.manager._bay_phases._body is None


def test_bay_body_scan_ignores_wide_side_hits_and_blocks_on_empty_scan():
    p = a_bay()
    p.manager.dock()
    svc = _services(p.manager)
    ranges = [3.0] * 360
    ranges[200] = 0.20  # 20 deg off forward (0.20*sin(20 deg)=0.068 m > band): side corridor clutter
    scan = {"ranges": ranges, "angle_min": -math.pi, "angle_increment": 2.0 * math.pi / 360,
            "range_min": 0.05, "range_max": 10.0}
    bay_body_scan(svc, scan, received_at=p.clock.now)
    body = p.manager._bay_phases._body
    assert body is not None and (body[1] is None or body[1] > 0.30)
    bay_body_scan(svc, _open_scan(rng=float("inf")), received_at=p.clock.now + 0.1)
    assert p.manager._bay_phases._body[1] == 0.0
