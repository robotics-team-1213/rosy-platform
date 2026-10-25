"""D-875 owner-local declarations and a planner-independent safety lifecycle."""

import ast
import asyncio
from pathlib import Path

import pytest

from fakes import FakeRelay, FakeRobot


def test_api_declarations_have_no_implementation_or_io_imports():
    import fleet.swarm

    api = Path(fleet.swarm.__file__).parent / "api"
    files = list(api.glob("*.py"))
    assert files, "the owner-local API must exist"
    allowed = ("__future__", "dataclasses", "enum", "typing", "core_common.", "fleet.swarm.api")
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(name.name.startswith(allowed) for name in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.level == 1 and node.module in (None, "types", "ports")
                        or not node.level and (node.module or "").startswith(allowed)), path


def test_legacy_exports_are_the_same_api_objects():
    from fleet.swarm.api import types, ports
    from fleet.formation import geometry, assignment
    from fleet.swarm import arming, session, session_state, transport

    for name in ("Formation", "FormationError", "SlotOffset"):
        assert getattr(geometry, name) is getattr(types, name)
    for name in ("FormationSpec", "SessionError", "ArmingFailed", "MapMismatch", "InvalidFormation"):
        assert getattr(arming, name) is getattr(types, name)
        assert getattr(session, name) is getattr(types, name)
    for name in ("SessionState", "HoldPolicy"):
        assert getattr(session_state, name) is getattr(types, name)
        assert getattr(session, name) is getattr(types, name)
    for name in ("RobotClient", "ReferenceSink", "RobotApiError"):
        assert getattr(transport, name) is getattr(ports, name)
    assert assignment.SlotAssigner is ports.SlotAssigner


def test_planner_runs_once_before_relay_and_stop_never_calls_it():
    from fleet.formation.geometry import Formation
    from fleet.swarm.arming import FormationSpec, plan_assignment
    from fleet.swarm.session import FormationSession, SessionState

    async def exercise():
        log = []
        leader, follower = FakeRobot("one", log=log), FakeRobot("two", log=log)
        session = FormationSession(leader, [follower], FormationSpec(Formation.COLUMN),
            relay_factory=lambda lead, followers, **kw: FakeRelay(lead, followers, log=log))
        plans = []

        def observed(*args, **kwargs):
            assert not any(row[0] == "relay" or row[1] == "follow" for row in log)
            plans.append(True)
            return plan_assignment(*args, **kwargs)

        session._plan_assignment = observed
        await session.start()
        assert plans == [True]
        session._plan_assignment = lambda *args, **kwargs: pytest.fail("stop invoked planning")
        await session.stop()
        assert session.state is SessionState.STOPPED
    asyncio.run(exercise())


def test_emergency_preflight_precedes_planning_and_streams():
    from fleet.formation.geometry import Formation
    from fleet.swarm.arming import FormationSpec, ArmingFailed
    from fleet.swarm.session import FormationSession

    async def exercise():
        leader = FakeRobot("one", state={"robot_id": "one", "mode": "EMERGENCY"})
        follower = FakeRobot("two")
        session = FormationSession(leader, [follower], FormationSpec(Formation.COLUMN))
        session._plan_assignment = lambda *args, **kwargs: pytest.fail("emergency invoked planning")
        with pytest.raises(ArmingFailed) as error:
            await session.start()
        assert error.value.code == "EMERGENCY_ACTIVE"
        assert session.relay is None
        assert not any(call[0] == "follow" for call in follower.calls)
    asyncio.run(exercise())
