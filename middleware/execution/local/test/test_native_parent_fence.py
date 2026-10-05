"""Host negatives for the test-only native parent composition, no ROS/device."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from test_omx_policy_session import setup_session
from native_parent_chain import SessionSubmissionFence
from omx_adapter.action_runner import ActionRunner, DriverSubmission, parse_action_grant
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import JointStateSnapshot
from test_omx_action_api import _grant
from core_common.protocol.schemas import LocalStopRequest, StopRequestSource


@pytest.mark.parametrize("denial", [None, "fence", "stop", "expiry"])
def test_preparation_allows_real_observation_and_poll_but_preserves_final_denial(
        tmp_path, monkeypatch, denial):
    session, _, _, _, _ = setup_session(tmp_path)
    config = session.owner.config
    store = ActionStore(tmp_path / "owner.sqlite3")
    grant = parse_action_grant(_grant(
        workcell_id=config.workcell_id, instance_id=config.instance_id,
        dispatch_generation=7,
    ))
    clock = [grant.issued_at]
    authority = [True]
    submissions = []

    class Driver:
        def submit(self, value):
            assert session._snapshot.sequence == 11
            submissions.append(value.action_id)
            return DriverSubmission(None, None)

    runner = ActionRunner(
        store, Driver(), workcell_id=config.workcell_id, instance_id=config.instance_id,
        principal_for_peer=lambda uid: "isolated-fleet-fixture", allowed_peer_uids={1001},
        current_fence=lambda epoch, generation: authority[0],
        capability_current=lambda value: True,
        submission_fence=SessionSubmissionFence(session), enabled=True,
        now=lambda: clock[0],
    )
    original = store.begin_submission

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        # Both calls use the genuine session lock/guards and must progress
        # before the final submission fence is acquired by this thread.
        with ThreadPoolExecutor(max_workers=2) as workers:
            observed = workers.submit(session.observe, JointStateSnapshot(
                {"joint_1": 0.1, "joint_2": 0.0}, 11, 10.0, "cal-7",
            ))
            polled = workers.submit(session.poll)
            observed.result(timeout=3)
            polled.result(timeout=3)
        if denial == "fence":
            authority[0] = False
        elif denial == "stop":
            session.fence.trip(LocalStopRequest(
                workcell_id=config.workcell_id, instance_id=config.instance_id,
                authority_epoch=2, dispatch_generation=7,
                reason="operator_stop", requested_at=datetime.now(timezone.utc),
            ), source=StopRequestSource.OPERATOR_LOCAL)
        elif denial == "expiry":
            clock[0] = grant.expires_at
        return result

    monkeypatch.setattr(store, "begin_submission", prepare)
    receipt = runner.submit(grant, peer_uid=1001)
    assert session._snapshot.sequence == 11
    assert submissions == ([] if denial else [grant.action_id])
    assert receipt["state"] == ("HOLD" if denial in {"fence", "stop"} else "UNKNOWN")
    assert receipt["driver_goal_id"] is None
    # A durable denied/uncertain attempt never becomes a second dispatch.
    if denial == "expiry":
        clock[0] = grant.issued_at
    if denial == "fence":
        authority[0] = True
    again = runner.submit(grant, peer_uid=1001)
    assert not again["created"]
    assert submissions == ([] if denial else [grant.action_id])
