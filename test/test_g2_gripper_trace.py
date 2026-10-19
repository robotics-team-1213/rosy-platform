"""Gripper evidence cannot replace canonical readback or block its control path."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/robot/omx'))
import g2_gripper_trace as module


def inputs():
    state = NS(positions={'gripper': .3, 'joint1': .1}, sequence=7, received_at=10.)
    profile = NS(gripper_joint='gripper', gripper_open=.8, start_state_tolerance_rad=.01,
                 max_joint_state_age_s=.5, gripper_close_for_width=lambda width: .1,
                 gripper_contact_for_width=lambda width: .3)
    owner = NS(runtime=NS(latest_joint_state=state, monotonic=lambda: 10.1), profile=profile)
    grant = NS(action_id='action', attempt_id='attempt', cell_transfer=NS(
        recipe_sha256='a' * 64, item_key='box', item='box1'))
    observation = NS(state='CLOSED', object_present=True, object_id='box1', sequence=7,
                     received_at=10., owner_generation=2)
    return owner, grant, observation


def test_read_preserves_canonical_object_and_records_same_joint_state(tmp_path):
    owner, grant, observation = inputs()
    calls = []
    trace = module.GripperReadbackTrace(tmp_path)
    trace.bind_recipe({'recipe_sha256': 'a' * 64, 'items': {'box': {'grasp_width_m': .05}}})

    def canonical(actual_owner, state, actual_grant):
        calls.append((actual_owner, state, actual_grant))
        return observation

    try:
        assert trace.read(owner, grant, canonical) is observation
    finally:
        assert trace.close(timeout=1.)
    assert calls == [(owner, owner.runtime.latest_joint_state, grant)]
    record = json.loads((tmp_path / '001.json').read_text())
    assert record['diagnostic_only'] is True
    assert record['joint_sequence'] == observation.sequence
    assert record['accepted_grasp_width_m'] == .05
    assert record['geometry_binding'] == 'ACCEPT_RECIPE_RECEIPT'
    assert record['observation']['object_id'] == observation.object_id


def test_read_preserves_original_exception_without_persisting_private_error(tmp_path):
    owner, grant, _ = inputs()
    error = RuntimeError('PRIVATE_INPUT_MUST_NOT_BE_RECORDED')
    trace = module.GripperReadbackTrace(tmp_path)

    def canonical(*args):
        raise error

    try:
        with pytest.raises(RuntimeError) as caught:
            trace.read(owner, grant, canonical)
        assert caught.value is error
    finally:
        assert trace.close(timeout=1.)
    text = (tmp_path / '001.json').read_text()
    assert 'PRIVATE_INPUT' not in text
    assert json.loads(text)['canonical_error_type'] == 'RuntimeError'


def test_writer_failure_does_not_change_canonical_readback(tmp_path, monkeypatch):
    owner, grant, observation = inputs()

    def fail(*args):
        raise OSError('disk unavailable')

    monkeypatch.setattr(module, '_write_record', fail)
    trace = module.GripperReadbackTrace(tmp_path)
    try:
        assert trace.read(owner, grant, lambda *args: observation) is observation
    finally:
        assert trace.close(timeout=1.)
    assert trace.status()['failure_code'] == 'WRITE_FAILED'


@pytest.mark.parametrize('raises', [False, True])
def test_failed_diagnostic_clock_sample_preserves_canonical_result(tmp_path, monkeypatch, raises):
    owner, grant, observation = inputs()
    samples, calls = [], []
    error = RuntimeError('canonical readback failed')

    def sample():
        samples.append(None)
        if len(samples) == 1:
            raise OSError('diagnostic clock unavailable')
        return 30.

    def canonical(*args):
        calls.append(args)
        if raises:
            raise error
        return observation

    monkeypatch.setattr(module.time, 'monotonic', sample)
    trace = module.GripperReadbackTrace(tmp_path)
    try:
        if raises:
            with pytest.raises(RuntimeError) as caught:
                trace.read(owner, grant, canonical)
            assert caught.value is error
        else:
            assert trace.read(owner, grant, canonical) is observation
        assert len(calls) == 1
    finally:
        assert trace.close(timeout=1.)
    assert trace.status()['failure_code'] == 'STEADY_SAMPLE_FAILED'
    assert json.loads((tmp_path / '001.json').read_text())['read_started_steady'] is None


def test_blocked_writer_has_bounded_records_and_shutdown(tmp_path, monkeypatch):
    owner, grant, observation = inputs()
    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        assert release.wait(3.)

    monkeypatch.setattr(module, '_write_record', blocked)
    trace = module.GripperReadbackTrace(tmp_path, max_records=2)
    try:
        assert trace.read(owner, grant, lambda *args: observation) is observation
        assert entered.wait(1.)
        for _ in range(2):
            assert trace.read(owner, grant, lambda *args: observation) is observation
        assert trace.status()['issued'] == 2
        assert trace.status()['failure_code'] == 'RECORD_LIMIT'
        assert trace.close(timeout=.01) is False
    finally:
        release.set()
        assert trace.close(timeout=1.)
