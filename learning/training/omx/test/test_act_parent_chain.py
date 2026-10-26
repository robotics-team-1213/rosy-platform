"""Same input/result to parent journal; HOST callbacks are not ROS acceptance."""
import sys
import base64
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/p) for p in ('learning/training/omx/test',
    'middleware/robot_execution/local/test', 'middleware/devices/omx/adapter/test', 'operations/fleet')]
from test_act_owner_capture import case, infer_for_owner
from test_policy_runtime_binding import runtime_methods
from native_parent_chain import submit_parent, export_parent
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from omx_adapter.ros_goal_contract import RosGoalEvent


@pytest.mark.parametrize('fault', [None, 'revoked'])
@pytest.mark.parametrize('actual_cpu', [False, True], ids=['fake_predictor', 'actual_cpu_synthetic'])
def test_original_inference_candidate_is_the_parent_submission(tmp_path, monkeypatch, fault, actual_cpu):
    session, engine, packet, client, _, authority, _, _, root = case(tmp_path, monkeypatch)
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session._execution_journal = journal
    runtime = runtime_methods(session, client)
    engine._clock = session._clock  # Establish the same fixture clock before capture.
    if actual_cpu:
        monkeypatch.undo()
        # Keep acquisition and observation on the declared fixed HOST fixture clock.
        monkeypatch.setattr('sim_policy_inference.perf_counter_ns', lambda: int(session._clock() * 1e9))
        from act_cpu_fixture import install_cpu_fixture
        engine = install_cpu_fixture(session, root)
    session.bind_runtime(runtime)  # Freeze the final installed source, after fixture setup.
    goal = str(uuid4())
    send = client.send_goal
    def accepted(command):
        runtime._dispatch_goal_event(RosGoalEvent('GOAL_ACCEPTED', command.command_id,
                                                None, goal, 10., 1))
        return send(command)
    client.send_goal = accepted
    results = []
    def capture_result():
        assert session.lease.identity.request_digest != 'a'*64
        candidate, result = infer_for_owner(engine, session, packet)
        results.append(result)
        if fault: authority[0] = False
        return candidate
    if fault:
        with pytest.raises(AssertionError):
            submit_parent(session, journal, tmp_path, candidate_factory=capture_result)
        assert len(results) == 1 and results[0].consumed_current and not authority[0]
        assert results[0].source.frame_sha256 == packet.metadata.frame_sha256
        if actual_cpu: assert results[0].positions == (0.,0.)
        assert not client.commands and session.hold_reason
        original = json.loads((tmp_path/'initial-owner-readback.json').read_bytes())
        assert original['receipt']['state'] == 'UNKNOWN' and original['receipt']['driver_goal_id'] is None
        return
    command, runner, api, parent = submit_parent(session, journal, tmp_path,
                                               candidate_factory=capture_result)
    assert len(results) == len(client.commands) == 1
    if actual_cpu: assert results[0].positions == (0., 0.)
    result_doc = asdict(results[0])
    result_doc['source']['rgb_base64'] = base64.b64encode(result_doc['source'].pop('rgb')).decode('ascii')
    (tmp_path/'inference-result.json').write_text(json.dumps(dict(
        result=result_doc, actual_cpu=actual_cpu, synthetic_model=True,
        clock_scope='fixed HOST fixture; not device/native timing'), indent=2), encoding='utf-8')
    record = journal.read(command)
    actual = record['intent']['candidate']
    expected = results[0].candidate_fields()
    for key, value in expected.items():
        assert actual[key] == (list(value) if isinstance(value, tuple) else value)
    runtime._dispatch_goal_event(RosGoalEvent('TERMINAL_RESULT', command, None,
                                            goal, 10.01, 2, status=4, result_code=0))
    proof = export_parent(tmp_path, journal, command, runner, api, parent, revoke=False)
    assert proof['driver_goal_id'] == goal and proof['task_outcome'] == 'unknown'
    assert proof['model_inference_verified'] is False  # Existing Episode semantics unchanged.
    from fleet.server.learning_receiver import LearningReceiver
    receiver_path = tmp_path/'receiver.sqlite3'
    inputs = (tmp_path/'fleet.json', tmp_path/'episode/manifest.json',
              tmp_path/'episode/owner-receipts/000000.json')
    receiver = LearningReceiver(receiver_path)
    received = receiver.ingest(*inputs)
    assert received['created'] and received['authentication'] == 'not_verified'
    revision = received['export']['revision']
    assert not receiver.ingest(*inputs)['created']
    assert LearningReceiver(receiver_path).get(revision) == receiver.get(revision)
    assert received['export']['receipt']['driver_goal_id'] == goal
