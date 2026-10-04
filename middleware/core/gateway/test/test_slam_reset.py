"""NAV-005 `POST /api/v1/slam/reset` — the endpoint must not claim success.

It used to return `{"reset": true}` unconditionally. Two independent paths lied:
the session guard returned silently when no mapping session was open, and the
executor call sat behind a `hasattr` that `RosBridge` never satisfied because it
implements no `reset_mapping` at all. A Fleet reading CAP-001 saw `slam: true`,
called the route, got 200, and nothing happened.

CAP-003 (`docs/spec/ROSY CORE SRS.md`) requires a clear code rather than a
general failure for an unsupported command, and the docking path already uses
501 for exactly this. These tests pin both answers and, as importantly, pin that
a refused reset leaves no trace: no `slam.started`, no session state change.
"""

from __future__ import annotations

import pytest

from core_features.navigation.manager import NavigationError

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


class RefusingExecutor:
    """A bridge that declares the contract member and cannot honour it.

    This is `RosBridge` today: the runtime has no slam_toolbox, so the method
    exists to fail with a code rather than to be missing and fail with 500.
    """

    def send_goal(self, spec):
        raise AssertionError("reset must not send a goal")

    def cancel_goal(self):
        raise AssertionError("reset must not cancel a goal")

    def send_initial_pose(self, x, y, yaw):
        raise AssertionError("reset must not touch localization")

    def save_map(self, name):
        raise AssertionError("reset must not save a map")

    def reset_mapping(self):
        raise NavigationError(
            "CAPABILITY_NOT_SUPPORTED",
            "slam_toolbox reset is not implemented in this runtime")


class RecordingExecutor(RefusingExecutor):
    """`RefusingExecutor` that counts resets instead of refusing them.

    For assertions about whether a path was *reached*, where refusing would be
    indistinguishable from never arriving.
    """

    def __init__(self) -> None:
        self.reset_calls = 0

    def reset_mapping(self):
        self.reset_calls += 1


@pytest.fixture
def events(request):
    """Collect published event types so a test can assert nothing was emitted."""
    seen: list[str] = []

    def attach(services):
        services.events.subscribe(lambda event: seen.append(event.type))
        return seen

    return attach


def test_reset_without_an_executor_is_501_and_publishes_nothing(core_client, events):
    client, svc = core_client()
    svc.nav.start_mapping(source="test")
    seen = events(svc)

    response = client.post("/api/v1/slam/reset", headers=OPERATOR)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert "slam.started" not in seen


def test_reset_with_an_executor_that_cannot_reset_is_501_and_publishes_nothing(
        core_client, events):
    client, svc = core_client()
    svc.nav.executor = RefusingExecutor()
    svc.nav.start_mapping(source="test")
    seen = events(svc)

    response = client.post("/api/v1/slam/reset", headers=OPERATOR)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    assert "slam.started" not in seen


def test_capability_gate_refuses_before_the_manager_is_reached(core_client):
    """The pre-existing 501 and the new one have different causes.

    Status code cannot tell them apart: with no executor the manager path also
    answers 501 `CAPABILITY_NOT_SUPPORTED` and publishes nothing, so a test that
    asserts only the code passes even when the gate has been moved below the
    call. The discriminating fact is that the executor is never reached — so the
    setup removes every *other* reason to refuse (an executor is present and a
    session is open) and asserts the call count.
    """
    client, svc = core_client(capabilities={"slam": False})
    svc.nav.executor = executor = RecordingExecutor()
    svc.nav.mapping_active = True

    response = client.post("/api/v1/slam/reset", headers=OPERATOR)

    assert response.status_code == 501
    assert executor.reset_calls == 0


def test_moving_goal_still_refuses_while_a_mapping_session_is_open(core_client):
    """SWM-001's guard is the neighbour of the code Step 2 rewrote.

    `moving_goal()` reads `mapping_active` too. Pinned here so a change to the
    mapping session's error handling cannot quietly open a path for swarm
    follow to drive during a survey.
    """
    from core_features.navigation.manager import NavGoalSpec

    _client, svc = core_client()
    svc.nav.executor = RefusingExecutor()
    svc.nav.start_mapping(source="test")

    with pytest.raises(NavigationError) as raised:
        svc.nav.moving_goal(NavGoalSpec(x=1.0, y=0.0, yaw=0.0), source="swarm")

    assert raised.value.code == "MAPPING_ACTIVE"


def test_reset_without_an_open_session_is_400_not_a_quiet_200(core_client, events):
    """The second of the two lies.

    Resetting outside a mapping session used to return early and still answer
    200. `save_map` already had the honest answer for the same condition, so
    this reuses its error rather than inventing a second vocabulary for one
    situation.
    """
    client, svc = core_client()
    svc.nav.executor = RefusingExecutor()
    seen = events(svc)

    assert svc.nav.mapping_active is False
    response = client.post("/api/v1/slam/reset", headers=OPERATOR)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert seen == []


def test_no_executor_and_no_session_answers_the_capability_first(core_client):
    """CAP-003: the capability answer precedes the session answer.

    Both guards fire here, and this is the only combination that separates the
    two orders — every other test supplies an executor or opens a session, which
    disarms one guard and lets either order pass. Reverse the two lines in
    `NavigationManager.reset_mapping` and this 501 becomes a 400: "this runtime
    cannot do that" reported as "your request was malformed".
    """
    client, svc = core_client()

    assert svc.nav.executor is None
    assert svc.nav.mapping_active is False
    response = client.post("/api/v1/slam/reset", headers=OPERATOR)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
