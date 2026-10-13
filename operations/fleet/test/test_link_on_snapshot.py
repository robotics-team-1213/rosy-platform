"""D-499: snapshot stamps link from the gather exception. No second probe."""

import httpx

from fakes import FakeRobot, run
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError


def _console(robot, scheme):
    endpoint = RobotEndpoint(robot_id=robot.robot_id,
                             base_url="%s://127.0.0.1:8080" % scheme, token="t")
    return FleetConsole([endpoint], [robot])


def test_a_successful_gather_is_up_and_a_401_is_tls_refused():
    up = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    row = run(_console(up, "http").snapshot())["robots"][0]
    assert row["online"] is True and row["link"] == "up"

    refused = FakeRobot("rosy_02")
    refused.state_error = RobotApiError("rosy_02", 401, "UNAUTHORIZED", "bad token")
    row = run(_console(refused, "https").snapshot())["robots"][0]
    assert row["online"] is False and row["link"] == "tls-refused"
    assert row["error"]["code"] == "UNAUTHORIZED"


def test_a_non_401_robot_api_error_omits_link():
    robot = FakeRobot("rosy_01")
    robot.state_error = RobotApiError("rosy_01", 500, "HTTP_500", "boom")
    row = run(_console(robot, "http").snapshot())["robots"][0]
    assert "link" not in row
    assert row["error"]["reachable"] is True


def test_plain_http_remote_protocol_error_is_protocol_and_https_is_unreachable():
    plain = FakeRobot("rosy_01")
    plain.state_error = httpx.RemoteProtocolError("disconnected")
    assert run(_console(plain, "http").snapshot())["robots"][0]["link"] == "protocol"

    secure = FakeRobot("rosy_02")
    secure.state_error = httpx.RemoteProtocolError("disconnected")
    assert run(_console(secure, "https").snapshot())["robots"][0]["link"] == "unreachable"


def test_a_read_that_fails_soon_after_an_answer_is_degraded_not_unreachable():
    # Site 2026-10-09: 3-5 s gathers on loaded robots flipped the card offline and back.
    now = {"t": 100.0}
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    endpoint = RobotEndpoint(robot_id="rosy_01", base_url="https://127.0.0.1:8080", token="t")
    console = FleetConsole([endpoint], [robot], clock=lambda: now["t"])
    assert run(console.snapshot())["robots"][0]["link"] == "up"

    robot.state_error = httpx.ReadTimeout("slow")
    now["t"] = 104.0
    row = run(console.snapshot())["robots"][0]
    assert row["online"] is False            # every decision still sees a lost read
    assert row["link"] == "degraded" and row["link_degraded_s"] == 4.0

    now["t"] = 111.0                         # past the 10 s grace: a real loss
    row = run(console.snapshot())["robots"][0]
    assert row["link"] == "unreachable" and "link_degraded_s" not in row


def test_a_robot_never_answered_is_unreachable_not_degraded():
    robot = FakeRobot("rosy_01")
    robot.state_error = httpx.ConnectError("down")
    row = run(_console(robot, "https").snapshot())["robots"][0]
    assert row["link"] == "unreachable"


def test_address_status_is_read_once_and_a_provider_failure_keeps_the_row():
    robot = FakeRobot("rosy_01")
    robot.state_error = httpx.ConnectError("down")
    console = _console(robot, "http")
    calls = {"n": 0}

    def status():
        calls["n"] += 1
        return {"rosy_01": "seen_at_other_address"}

    console.set_link_address_status(status)
    row = run(console.snapshot())["robots"][0]
    assert calls["n"] == 1 and row["link"] == "moved"

    def blow():
        raise RuntimeError("scan store")

    console.set_link_address_status(blow)
    row = run(console.snapshot())["robots"][0]
    assert row["robot_id"] == "rosy_01" and row["link"] == "unreachable"
