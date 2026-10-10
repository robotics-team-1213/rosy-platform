"""D-621: explicit image-space autonomy, without synthesizing driver holds."""
import dataclasses

import pytest

from core_features.line_follow.manager import LineFollowMode, LineObservation

OP = {"Authorization": "Bearer rosy-dev-operator"}
VIEW = {"Authorization": "Bearer rosy-dev-viewer"}


def _ready(core_client):
    client, svc = core_client()
    clock = {"t": 100.0}
    svc.line_follow.bind_clock(lambda: clock["t"])
    svc.line_follow.observe_clearance(1.0, clock["t"])
    observation = LineObservation(LineFollowMode.CAMERA_LINE, clock["t"], True, 0.1, 0.9,
                                  camera_strategy="between")
    svc.line_follow.observe(observation, received_at=clock["t"], source_now=clock["t"])
    return client, svc, clock, observation


def test_missing_evidence_refuses_start_without_changing_mode(core_client):
    client, svc = core_client()
    response = client.put('/api/v1/line-follow/mode', headers=OP,
                          json={"mode": "CAMERA_LINE", "autonomous": True})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'LINE_AUTONOMY_NOT_READY'
    assert svc.modes.mode.value == 'IDLE' and not svc.line_follow.active


def test_between_starts_without_hold_and_runs_past_two_seconds(core_client):
    client, svc, clock, observation = _ready(core_client)
    ready = client.get('/api/v1/line-follow/readiness', headers=VIEW)
    assert ready.status_code == 200 and ready.json()['ready'] is True
    response = client.put('/api/v1/line-follow/mode', headers=OP,
                          json={"mode": "CAMERA_LINE", "autonomous": True})
    assert response.status_code == 200 and not svc.line_follow.hold_required
    clock['t'] += 3.0
    svc.line_follow.observe_clearance(1.0, clock['t'])
    svc.line_follow.observe(dataclasses.replace(observation, stamp=clock['t']),
                            received_at=clock['t'], source_now=clock['t'])
    decision = svc.line_follow.tick()
    assert 0 < decision.linear <= 0.04
    assert svc.line_follow.active
    clock['t'] += 1.0
    stopped = svc.line_follow.tick()
    assert stopped.linear == 0 and stopped.angular == 0


def test_replay_cannot_refresh_preflight_camera(core_client):
    _, svc, clock, observation = _ready(core_client)
    clock['t'] += 1.0
    svc.line_follow.observe(observation, received_at=clock['t'])
    assert svc.line_follow.camera_auto_readiness()['ready'] is False


def test_invalid_camera_while_off_clears_readiness(core_client):
    _, svc, _, _ = _ready(core_client)
    svc.line_follow.invalidate()
    assert svc.line_follow.camera_auto_readiness()['ready'] is False


@pytest.mark.parametrize('ground', [None, 'NOMINAL'])
def test_legacy_or_nominal_evidence_does_not_gain_autonomy(core_client, ground):
    client, svc, clock, observation = _ready(core_client)
    clock['t'] += 0.01
    svc.line_follow.observe(dataclasses.replace(observation, stamp=clock['t'], ground=ground,
                                                camera_strategy=None), received_at=clock['t'])
    rejected = client.put('/api/v1/line-follow/mode', headers=OP,
                          json={"mode": "CAMERA_LINE", "autonomous": True})
    assert rejected.status_code == 409 and not svc.line_follow.active


def test_stale_evidence_at_command_submission_zeroes_motion(core_client):
    client, svc, clock, observation = _ready(core_client)
    assert client.put('/api/v1/line-follow/mode', headers=OP,
                      json={"mode": "CAMERA_LINE", "autonomous": True}).status_code == 200
    svc.line_follow.observe(dataclasses.replace(observation, stamp=100.01), received_at=100.01)
    clock['t'] = 100.02
    decision = svc.line_follow.tick()
    assert decision.linear > 0
    clock['t'] += 1.0
    writes = []
    svc.line_follow.apply_if_current(decision, writes.append)
    assert not writes or (writes[-1].linear == 0 and writes[-1].angular == 0)
