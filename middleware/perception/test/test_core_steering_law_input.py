"""Native camera consumes only CORE's public effective steering-law hand-over."""
from datetime import datetime, timezone
import json
import os

import pytest


LAW = dict(cruise_speed=.10, max_linear=.10, steering_gain=2., min_confidence=.35)
NOW = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)


def _input():
    from control.core_law_input import CoreLawInput
    return CoreLawInput()


def _write(path, **changes):
    data = dict(schema=2, written_at=NOW.isoformat(), robot_id='rosy_02',
                core_process_id=42, line_follow_steering_law=LAW)
    data.update(changes)
    path.write_text(json.dumps(data))
    path.chmod(0o644)


def test_native_home_requires_core_handover_even_with_private_config_env():
    from control.core_law_input import native_law_required
    assert native_law_required(dict(ROSY_DEPLOYMENT='device', ROSY_CONFIG='/private/core.yaml'))
    assert native_law_required(dict(HOME='/var/lib/rosy/camera'))
    assert not native_law_required(dict(HOME='/home/ai', ROSY_CONFIG='/owned/sim.yaml'))


def test_actual_core_override_is_used_without_camera_home_yaml(tmp_path):
    path = tmp_path / 'status-inputs.json'
    _write(path)
    current = _input().read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    assert current.steering_law == dict(cruise_speed=.10, steering_gain=2., min_confidence=.35)


def test_sim_observer_uses_readonly_law_parameters_without_core_config(monkeypatch):
    from control.core_law_input import configure_drivable_law
    from types import SimpleNamespace
    monkeypatch.delenv('ROSY_DEPLOYMENT', raising=False)
    monkeypatch.setenv('HOME', '/home/sim')
    declared = []
    values = {'core_'+key: value for key, value in LAW.items()}
    node = SimpleNamespace(_paint_worker=SimpleNamespace(target='drivable'),
        declare_parameter=lambda *args: declared.append(args),
        get_parameter=lambda key: SimpleNamespace(value=values[key]))
    readonly = object()
    configure_drivable_law(node, readonly)
    assert len(declared) == 4 and all(row[2] is readonly for row in declared)
    assert node._native_core_law is None
    assert node._drivable_steer.steering_law['steering_gain'] == 2.


@pytest.mark.parametrize('changes', [dict(robot_id='rosy_01'), dict(written_at='2026-10-12T05:59:56+00:00'),
    dict(written_at='2026-10-12T06:00:01+00:00'), dict(written_at='2026-10-12T06:00:00'),
    dict(line_follow_steering_law=dict(LAW, steering_gain=float('nan'))),
    dict(line_follow_steering_law=dict(LAW, max_linear=.01)), dict(core_process_id=None)])
def test_invalid_or_stale_handover_drops_held_path(tmp_path, changes):
    path = tmp_path / 'status-inputs.json'
    _write(path)
    source = _input()
    old = source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    old._expected_path = object()
    _write(path, **changes)
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()) is None
    assert old._expected_path is None


def test_changed_law_or_core_restart_drops_previous_memory(tmp_path):
    path = tmp_path / 'status-inputs.json'
    source = _input()
    _write(path)
    first = source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    first._expected_path = object()
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()) is first
    _write(path, line_follow_steering_law=dict(LAW, steering_gain=.8))
    second = source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    assert second is not first and first._expected_path is None
    second._expected_path = object()
    _write(path, line_follow_steering_law=dict(LAW, steering_gain=.8), core_process_id=43)
    third = source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    assert third is not second and second._expected_path is None


def test_backwards_handover_timestamp_drops_memory_even_when_fresh(tmp_path):
    from datetime import timedelta
    path = tmp_path / 'status-inputs.json'
    source = _input()
    _write(path)
    old = source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid())
    old._expected_path = object()
    _write(path, written_at=(NOW-timedelta(seconds=1)).isoformat())
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()) is None
    assert old._expected_path is None


def test_native_missing_law_cannot_reuse_pixel_tracker_output():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    source = Path(__file__).resolve().parents[1] / 'sensors/line_observation/line_observer_node.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    guard = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and ast.unparse(n.test) == 'self._drivable_required and self._drivable_steer is None')
    keeper = SimpleNamespace(last={})
    env = dict(self=SimpleNamespace(_drivable_required=True, _drivable_steer=None, _lane_keeper=keeper),
               observation=object())
    exec(compile(ast.Module(body=[guard], type_ignores=[]), str(source), 'exec'), env)
    assert env['observation'] is None
    assert keeper.last['reason'] == 'core_steering_law_unavailable'


def test_waiting_for_native_law_still_subscribes_scan_and_route_prior():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from control.lane_route_guide_input import LaneRouteGuideInput, subscribe_route_guide
    from test_lane_route_guide_input import message
    source = Path(__file__).resolve().parents[1] / 'sensors/line_observation/line_observer_node.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    guard = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and n.body and isinstance(n.body[0], ast.Expr)
                 and ast.unparse(n.body[0].value).startswith('self.create_subscription(LaserScan'))
    topics = {}
    node = SimpleNamespace(_drivable_required=True, _drivable_steer=None, _on_scan=lambda _: None,
                           _lane_guide=LaneRouteGuideInput(), _stamp=lambda: 10.2,
                           create_subscription=lambda _, topic, callback, qos: topics.update({topic: callback}))
    exec(compile(ast.Module(body=[guard], type_ignores=[]), str(source), 'exec'),
         dict(self=node, LaserScan=object, String=object, qos_profile_sensor_data=None,
              subscribe_route_guide=subscribe_route_guide))
    assert list(topics) == ['scan', 'line/lane_guide']
    receive = topics['line/lane_guide']
    receive(SimpleNamespace(data=message()))
    assert node._lane_guide.for_frame(10.2).authority_seq == 3
    receive(SimpleNamespace(data=message(seq=2, clear=True)))
    receive(SimpleNamespace(data=message()))
    assert node._lane_guide.for_frame(10.3) is None


def test_missing_untrusted_or_symlink_file_is_refused(tmp_path):
    path = tmp_path / 'status-inputs.json'
    source = _input()
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()) is None
    _write(path)
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()+1) is None
    path.chmod(0o666)
    assert source.read(path, 'rosy_02', now=NOW, owner_uid=os.getuid()) is None
    link = tmp_path / 'alias.json'
    link.symlink_to(path)
    assert source.read(link, 'rosy_02', now=NOW, owner_uid=os.getuid()) is None
