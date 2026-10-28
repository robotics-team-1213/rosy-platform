"""Passive placement tracing never grants authority or hides the canonical result."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/robot/omx'))
ACTION = str(uuid.UUID(int=1))
ATTEMPT = str(uuid.UUID(int=2))
MODEL = 'cell_' + ACTION
POSE = dict(x_m=.2, y_m=.07, z_m=.025, roll_rad=0., pitch_rad=0., yaw_rad=3.1415)


def watch(model=MODEL):
    return dict(model=model, action_id=model[5:], attempt_id=ATTEMPT,
                baseline=POSE, baseline_observed_at=100., confirmation_seen_at=101.)


def test_trace_starts_only_after_confirmation_keeps_first_crossing_and_surrounding_samples():
    from g2_placement_trace import PlacementTrace
    trace = PlacementTrace()
    trace.observe(MODEL, {**POSE, 'y_m': 9.}, wall=99., steady=1., sim_clock=1.)
    trace.watch(**watch())
    for index in range(5):
        trace.observe(MODEL, POSE, wall=102.+index, steady=2.+index, sim_clock=2.+index)
    trace.observe(MODEL, {**POSE, 'y_m': .074}, wall=107., steady=7., sim_clock=7.)
    for index in range(100):
        trace.observe(MODEL, {**POSE, 'y_m': .1}, wall=108.+index, steady=8.+index, sim_clock=8.+index)
    record = trace.snapshot()['models'][MODEL]
    assert record['first_crossing']['observed_at'] == 107.
    assert record['first_crossing']['translation_m'] == pytest.approx(.004)
    assert len(record['before']) == 3 and len(record['after']) == 3
    assert record['baseline_observed_at'] == 100. and record['confirmation_seen_at'] == 101.
    assert record['registered_at'] >= 101.


def test_wrapping_orientation_and_duplicate_watch_do_not_reset_evidence():
    from g2_placement_trace import PlacementTrace
    trace = PlacementTrace()
    trace.watch(**watch())
    trace.observe(MODEL, {**POSE, 'yaw_rad': -3.1415}, wall=102., steady=2., sim_clock=2.)
    assert trace.snapshot()['models'][MODEL]['first_crossing'] is None
    trace.observe(MODEL, {**POSE, 'roll_rad': .1}, wall=103., steady=3., sim_clock=3.)
    trace.watch(**watch())
    assert trace.snapshot()['models'][MODEL]['first_crossing']['observed_at'] == 103.
    with pytest.raises(ValueError):
        trace.watch(**{**watch(), 'baseline': {**POSE, 'z_m': .04}})


def test_fixed_model_and_sample_caps_fit_existing_64k_ipc_and_exclude_private_values():
    from g2_placement_trace import PlacementTrace
    trace = PlacementTrace()
    for number in range(1, 17):
        model = 'cell_' + str(uuid.UUID(int=number))
        trace.watch(**watch(model))
        for index in range(20):
            trace.observe(model, {**POSE, 'y_m': .08 + index/100000., 'token': 'PRIVATE'},
                          wall=1792234182.4740834+index, steady=20000.123456789+index, sim_clock=111.198+index)
    with pytest.raises(ValueError):
        trace.watch(**watch('cell_' + str(uuid.UUID(int=17))))
    raw = json.dumps(trace.snapshot(), allow_nan=False)
    assert len(raw.encode()) < 65536
    assert 'PRIVATE' not in raw
    with pytest.raises(ValueError):
        PlacementTrace().watch(**{**watch(), 'baseline': {**POSE, 'x_m': float('nan')}})


def test_registration_requires_actual_confirmed_step_and_matching_saved_evidence(tmp_path):
    from g2_placement_trace import register_confirmed
    run = tmp_path
    (run/'placements').mkdir()
    submission = dict(mission_id='mission', evidence=dict(action_id=ACTION, attempt_id=ATTEMPT,
        step_index=0, model_id=MODEL, model_pose_base=POSE, observed_at=100.))
    (run/'placements'/(ACTION+'.json')).write_text(json.dumps(submission))
    step = dict(status='ACTION_SUCCEEDED', action_id=ACTION, attempt_id=ATTEMPT, step_index=0)
    calls = []
    register_confirmed(dict(mission_id='mission', steps=[step]), run, calls.append)
    assert calls == []
    step['status'] = 'GOAL_CONFIRMED'
    registered = set()
    register_confirmed(dict(mission_id='mission', steps=[step]), run, calls.append, registered=registered)
    register_confirmed(dict(mission_id='mission', steps=[step]), run, calls.append, registered=registered)
    assert len(calls) == 1 and calls[0]['operation'] == 'watch_placement'
    step['attempt_id'] = str(uuid.UUID(int=3))
    with pytest.raises(ValueError):
        register_confirmed(dict(mission_id='mission', steps=[step]), run, calls.append)
    assert len(calls) == 1


def test_observer_pose_stream_is_passive_and_trace_request_returns_bounded_measurements():
    from g2_observer import Observations
    state = Observations()
    request = dict(operation='watch_placement', **watch())
    assert state.request(request)['ok'] is True
    item = NS(name=MODEL, position=NS(x=.2, y=.08, z=.025), orientation=NS(w=1., x=0., y=0., z=0.))
    state.pose(NS(pose=[item]))
    record = state.request(dict(operation='placement_trace'))['trace']['models'][MODEL]
    assert record['first_crossing'] is not None
    assert state.models[MODEL][1]['y_m'] == .08


def test_terminal_collection_failure_is_visible_without_raising_or_changing_hold(tmp_path):
    from g2_placement_trace import persist_trace
    def failed(request):
        raise TimeoutError('PRIVATE')
    assert persist_trace(tmp_path, failed) is False
    result = json.loads((tmp_path/'placement-trace.json').read_text())
    assert result == {'schema': 'rosy.g2-placement-trace/1', 'collection': 'FAILED', 'error_type': 'TimeoutError'}


def test_collection_timeout_cannot_block_control_cleanup(tmp_path):
    import threading
    import time
    from g2_placement_trace import persist_trace
    release = threading.Event()
    def blocked(request):
        release.wait(3)
        raise TimeoutError()
    started = time.monotonic()
    try:
        assert persist_trace(tmp_path, blocked, timeout=.05) is False
        assert time.monotonic()-started < .5
    finally:
        release.set()


def test_registration_failure_is_attempted_once_and_never_masks_execution(tmp_path, monkeypatch):
    import g2_placement_trace as module
    registrar = module.TraceRegistration(tmp_path)
    calls = []
    def failed(*args, **kwargs):
        calls.append(True)
        raise TimeoutError('PRIVATE')
    monkeypatch.setattr(module, 'register_confirmed', failed)
    monkeypatch.setattr(module, 'write_json', failed)
    registrar.observe({}, lambda request: None)
    registrar.observe({}, lambda request: None)
    assert len(calls) == 1 and registrar.disabled is True
    assert registrar.failure == {'error_type': 'TimeoutError', 'diagnostic_only': True}


def test_registration_failure_cannot_wait_for_disk_before_canonical_hold_handling(tmp_path, monkeypatch):
    import threading
    import g2_placement_trace as module
    registrar = module.TraceRegistration(tmp_path)
    release, handled_hold = threading.Event(), threading.Event()
    def failed(*args, **kwargs):
        raise TimeoutError('PRIVATE')
    def parked_write(*args, **kwargs):
        release.wait(3)
    monkeypatch.setattr(module, 'register_confirmed', failed)
    monkeypatch.setattr(module, 'write_json', parked_write)
    def runner():
        registrar.observe({'status': 'HOLD'}, lambda request: None)
        handled_hold.set()
    worker = threading.Thread(target=runner)
    worker.start()
    try:
        assert handled_hold.wait(.3)
        assert registrar.failure == {'error_type': 'TimeoutError', 'diagnostic_only': True}
    finally:
        release.set()
        worker.join(1)


def test_registration_failure_is_persisted_only_by_bounded_terminal_worker(tmp_path):
    from g2_placement_trace import persist_trace
    failure = {'error_type': 'TimeoutError', 'diagnostic_only': True}
    assert persist_trace(tmp_path, lambda request: {'trace': {}}, registration_failure=failure)
    result = json.loads((tmp_path/'placement-trace.json').read_text())
    assert result['registration_failure'] == failure


def test_diagnostic_invalid_sample_does_not_break_existing_observer_pose_update():
    from g2_observer import Observations
    state = Observations()
    state.request(dict(operation='watch_placement', **watch()))
    item = NS(name=MODEL, position=NS(x=float('nan'), y=.08, z=.025), orientation=NS(w=1., x=0., y=0., z=0.))
    state.pose(NS(pose=[item]))
    assert state.request(dict(operation='placement_trace'))['trace']['diagnostic_failure_count'] == 1
