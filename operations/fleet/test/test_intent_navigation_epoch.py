"""Fleet must reject unsupported caller navigation epochs rather than replace them."""
from types import SimpleNamespace

import pytest

from core_common.intent import interpret
from fakes import run
from fleet.hub.hub import HubError
from fleet.server.intent_execution import IntentExecution, _robot_call

BOOT = "10000000-0000-0000-0000-000000000001"


def exercise(entry, supplied):
    effects = []

    async def goal(*args, **kwargs):
        effects.append(("goal", args, kwargs))
        return {"accepted": True}

    async def submit(**kwargs):
        effects.append(("task", kwargs))
        return {"task_id": "new-task", "status": "ACCEPTED"}

    console = SimpleNamespace(goal=goal)
    tasks = SimpleNamespace(submit_navigation=submit) if entry in {"step_task", "task_branch"} else None
    execution = IntentExecution(console, tasks, lambda *args, **kwargs: effects.append("fanout"),
                                lambda *args, **kwargs: effects.append("cancel"))
    call, = interpret({"do": "navigate", "robot": "robot", "x": 1.0, "y": 2.0, **supplied})
    principal = SimpleNamespace(principal_id="operator")
    if entry == "robot_call":
        continuation = _robot_call(console, call)
    elif entry == "task_branch":
        continuation = execution._step(call, principal, "once", 0)
    else:
        continuation = execution.step(call, principal, "once", 0)
    return continuation, effects, call


@pytest.mark.parametrize("entry", ["robot_call", "step_direct", "step_task", "task_branch"])
@pytest.mark.parametrize("supplied", [
    {"expected_boot_id": BOOT},
    {"expected_owner_generation": 1},
    {"expected_boot_id": BOOT, "expected_owner_generation": 1},
])
def test_caller_epoch_is_rejected_before_any_fleet_navigation_side_effect(entry, supplied):
    continuation, effects, call = exercise(entry, supplied)
    original = dict(call.body)
    with pytest.raises(HubError) as rejected:
        run(continuation)
    assert rejected.value.code == "COMMAND_REJECTED"
    assert "FLEET_NAVIGATION_CALLER_EPOCH_UNSUPPORTED" in str(rejected.value)
    assert effects == []
    assert call.body == original


@pytest.mark.parametrize("entry", ["robot_call", "step_direct", "step_task", "task_branch"])
def test_advisory_absence_still_reaches_the_existing_final_dispatch(entry):
    continuation, effects, _call = exercise(entry, {})
    assert run(continuation)["accepted"] is True
    assert len(effects) == 1
    assert effects[0][0] == ("task" if entry in {"step_task", "task_branch"} else "goal")
