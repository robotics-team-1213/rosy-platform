"""Run the teacher's actual finalization slice without ROS or actuator transports."""
import ast
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'deploy/robot/omx'))
import sim_pick_place_teacher as teacher


@pytest.fixture
def observation(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'middleware/devices/omx/adapter'))
    from omx_adapter.watchdog_observation import intake_observation, watchdog_observation
    intake = intake_observation(dict(stamp_ns=100, source_now_ns=120, received_at=10.,
        wall_received_at=20., accepted=True), callback_entered_steady=19.,
        intake_observed_steady=21., intake_sequence=7)
    return watchdog_observation('joint_state_stale', SimpleNamespace(command_id='teacher-1'),
        SimpleNamespace(sequence=6, received_at=9.),
        SimpleNamespace(max_joint_state_age_s=.5, action_timeout_s=3., wall_clock_bound_factor=4.),
        owner_now=10., steady_now=22., joint_wall=18., active_started_at=8.,
        active_wall=17., wall_now=None, intake=intake,
        owner_now_steady_before=21.5, owner_now_steady_after=21.6)


@pytest.mark.parametrize('diagnostic', ['valid', 'absent', 'malformed', 'raises', 'nonfinite'])
def test_teacher_final_receipt_keeps_watchdog_facts_and_always_closes(diagnostic, observation):
    calls, written = [], {}
    class Owner:
        @property
        def watchdog_observation(self):
            if diagnostic == 'raises':
                raise RuntimeError('private diagnostic must not enter the receipt')
            return dict(valid=observation, absent=None, malformed=object(),
                        nonfinite=replace(observation, owner_now=float('nan')))[diagnostic]
    owner = Owner()
    receipt = {'success': False, 'error': 'owner HOLD: joint_state_stale'}
    def write(path, value):
        written[path.name] = json.loads(json.dumps(value, allow_nan=False))
    def closed(name):
        return lambda: calls.append(name)
    namespace = dict(vars(teacher), receipt=receipt, success=False, error=receipt['error'],
        sim_time=lambda: 10., facade=SimpleNamespace(snapshot=lambda: {'owner_state': 'hold'}),
        capture=SimpleNamespace(camera_status=lambda: {}, source_pairing_error=None, camera=None),
        camera=SimpleNamespace(error=None, destroy=closed('camera')), arm=SimpleNamespace(owner=owner,
        destroy=closed('arm')), executor=SimpleNamespace(shutdown=closed('executor')),
        node=SimpleNamespace(destroy_node=closed('node')), rclpy=SimpleNamespace(shutdown=closed('rclpy')),
        samples=[], events=[], commands=[], directory=Path('/unused'), write_json=write)
    run = next(n for n in ast.parse(Path(teacher.__file__).read_text()).body
               if isinstance(n, ast.FunctionDef) and n.name == 'run')
    final = next(n.finalbody for n in ast.walk(run) if isinstance(n, ast.Try) and n.finalbody)
    exec(compile(ast.Module(body=final, type_ignores=[]), teacher.__file__, 'exec'), namespace)
    result = written['teacher-result.json']
    assert result['success'] is False and result['error'] == 'owner HOLD: joint_state_stale'
    assert calls == ['camera', 'executor', 'arm', 'node', 'rclpy']
    evidence = result['watchdog_observation']
    if diagnostic == 'valid':
        from dataclasses import asdict
        assert evidence == asdict(observation)
        assert evidence['intake']['intake_sequence'] == 7 and evidence['joint_sequence'] == 6
        assert evidence['owner_now_steady_after'] == 21.6
    elif diagnostic == 'absent':
        assert evidence is None
    else:
        assert set(evidence) == {'error'}
        assert evidence['error'] in ('TypeError', 'RuntimeError', 'ValueError')
