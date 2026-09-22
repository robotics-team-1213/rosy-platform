"""CLI 는 파싱과 배선만 한다. 실제 로봇은 Task 14 의 시뮬 계측이 본다."""

import asyncio
import io
from pathlib import Path

import pytest
from fakes import run

from fleet import cli
from fleet.formation.geometry import Formation
from fleet.swarm.robots import RobotEndpoint, write_robots
from fleet.swarm.session import FormationSpec, HoldPolicy, SessionError


def _write(tmp_path):
    p = tmp_path / "robots.yaml"
    write_robots(p, [RobotEndpoint("rosy_01", "http://a:8080", "t1"),
                     RobotEndpoint("rosy_02", "http://b:8080", "t2"),
                     RobotEndpoint("rosy_03", "http://c:8080", "t3")])
    return p


def test_formation_args_build_a_spec_and_split_leader_from_followers(tmp_path):
    p = _write(tmp_path)
    args = cli.parse_args(["formation", "--robots", str(p), "--leader", "rosy_02",
                           "--formation", "V", "--spacing", "0.7", "--max-speed", "0.12",
                           "--policy", "ABORT", "--grid-cols", "3"])
    leader, followers = cli.split_robots(args)
    assert leader.robot_id == "rosy_02"
    assert [f.robot_id for f in followers] == ["rosy_01", "rosy_03"]
    spec = cli.spec_from(args)
    assert spec == FormationSpec(Formation.V, spacing=0.7, grid_cols=3, max_speed=0.12,
                                 stream_timeout_ms=1000)
    assert cli.policy_from(args) is HoldPolicy.ABORT


def test_hub_is_not_a_registered_command():
    """dispatch 만 있고 subparser 가 없는 죽은 'hub' 경로는 제거됐다(통신 보고서 §5).
    허브 서버 자체는 create_hub_app 으로 테스트가 직접 연다."""
    with pytest.raises(SystemExit):
        cli.parse_args(["hub", "--listen"])
    source = (Path(cli.__file__).read_text(encoding="utf-8"))
    assert "run_hub" not in source
    assert 'args.command == "hub"' not in source


def test_an_unknown_leader_is_refused(tmp_path):
    p = _write(tmp_path)
    args = cli.parse_args(["formation", "--robots", str(p), "--leader", "rosy_09"])
    with pytest.raises(SystemExit):
        cli.split_robots(args)


def test_relay_defaults(tmp_path):
    p = _write(tmp_path)
    args = cli.parse_args(["relay", "--robots", str(p), "--leader", "rosy_01"])
    assert args.command == "relay"
    leader, followers = cli.split_robots(args)
    assert leader.robot_id == "rosy_01" and len(followers) == 2


def test_console_defaults_to_the_installable_web_common_assets(tmp_path):
    p = _write(tmp_path)
    args = cli.parse_args(["console", "--robots", str(p)])

    assert args.web_common.name == "web_common"
    assert (args.web_common / "tokens.css").is_file()
    assert (args.web_common / "core_ui_logic.js").is_file()


def test_console_commands_map_to_session_methods():
    class Recorder:
        def __init__(self):
            self.calls = []
            self.state = type("S", (), {"value": "RUNNING"})()
            self.reason = None
            self.pending_triggers = []

        async def reform(self, spec):
            self.calls.append(("reform", spec))

        async def resume(self):
            self.calls.append(("resume",))

        async def stop(self):
            self.calls.append(("stop",))

    rec = Recorder()
    base = FormationSpec(Formation.COLUMN, spacing=0.6)
    assert run(cli.handle_command("reform LINE 0.8", rec, base)) is True
    assert run(cli.handle_command("resume", rec, base)) is True
    assert run(cli.handle_command("status", rec, base)) is True
    assert run(cli.handle_command("stop", rec, base)) is False
    assert rec.calls[0] == ("reform", FormationSpec(Formation.LINE, spacing=0.8))
    assert rec.calls[1:] == [("resume",), ("stop",)]


def test_a_bad_console_command_does_not_end_the_session():
    class Recorder:
        state = type("S", (), {"value": "RUNNING"})()
        reason = None
        pending_triggers = []

    base = FormationSpec(Formation.COLUMN, spacing=0.6)
    assert run(cli.handle_command("reform TRIANGLE", Recorder(), base)) is True
    assert run(cli.handle_command("dance", Recorder(), base)) is True


def test_resume_while_already_running_says_so(capsys):
    """RUNNING 에서 resume 은 세션 쪽에서 무해한 no-op 이다. 콘솔이 조용하면 운영자는
    명령이 씹혔는지 이미 달리고 있는지 알 수 없다."""
    class Recorder:
        def __init__(self):
            self.calls = []
            self.state = type("S", (), {"value": "RUNNING"})()
            self.reason = None
            self.pending_triggers = []

        async def resume(self):
            self.calls.append(("resume",))

    rec = Recorder()
    base = FormationSpec(Formation.COLUMN, spacing=0.6)
    assert run(cli.handle_command("resume", rec, base)) is True
    assert rec.calls == [("resume",)]                 # 세션에게는 그대로 넘긴다
    assert capsys.readouterr().out.strip() == "already running"


def test_a_refused_reform_is_printed_and_the_console_keeps_going(capsys):
    """사전 점검 거절은 세션을 그대로 둔다. 콘솔도 그대로 열려 있어야 한다."""
    class Refusing:
        def __init__(self):
            self.state = type("S", (), {"value": "RUNNING"})()
            self.reason = None
            self.pending_triggers = []

        async def reform(self, spec):
            raise SessionError("FOLLOW is a single follower; use COLUMN for more")

    base = FormationSpec(Formation.COLUMN, spacing=0.6)
    assert run(cli.handle_command("reform FOLLOW", Refusing(), base)) is True
    assert capsys.readouterr().out.startswith("refused:")


def test_a_reform_that_ends_in_a_hold_says_so(capsys):
    """reform 이 재개하지 않고 끝났다는 것을 운영자가 다음 통계 줄까지 기다려 알면 늦다."""
    class Held:
        def __init__(self):
            self.state = type("S", (), {"value": "HOLDING"})()
            self.reason = ("safety.estop", "rosy_03")

        async def reform(self, spec):
            self.reformed = spec

    held = Held()
    base = FormationSpec(Formation.COLUMN, spacing=0.6)
    assert run(cli.handle_command("reform LINE", held, base)) is True
    out = capsys.readouterr().out
    assert out.startswith("held:")
    assert "safety.estop" in out


def test_the_stdin_reader_queues_every_line_and_turns_eof_into_a_stop():
    """EOF 는 파이프가 닫힌 것이다 — 명령을 줄 사람이 없으니 대형을 푼다. 큐에 아무것도
    넣지 않고 조용히 끝나면 콘솔은 무장된 대형을 붙잡은 채 통계만 찍는다."""
    async def main():
        commands: asyncio.Queue = asyncio.Queue()
        cli._start_stdin_reader(commands, io.StringIO("status\nresume\n"))
        # 타임아웃은 벽시계 대기가 아니라 매달리지 않기 위한 안전핀이다 — 줄은 스레드가
        # 넣는 즉시 온다.
        return [await asyncio.wait_for(commands.get(), timeout=5.0) for _ in range(3)]

    assert run(main()) == ["status\n", "resume\n", "stop"]


def test_a_session_that_stopped_on_its_own_ends_the_console_at_once(capsys):
    """ABORT 정책이나 중단된 reform 은 세션을 스스로 끝낸다. 콘솔이 1 s 통계 줄을 계속
    찍으면 운영자는 대형이 이미 풀린 것을 모른 채 앉아 있다."""
    class Stopped:
        state = type("S", (), {"value": "STOPPED"})()
        reason = ("nav.stuck", "rosy_02")

        def reason_text(self):
            return "nav.stuck (rosy_02)"

    printed = []
    base = FormationSpec(Formation.COLUMN, spacing=0.6)

    async def main():
        await asyncio.wait_for(
            cli.formation_console(Stopped(), base, asyncio.Queue(), lambda: printed.append(1)),
            timeout=5.0)

    run(main())
    assert printed == []                     # 통계 줄 하나 없이, 1 s 를 기다리지도 않고 나온다
    assert "session stopped: nav.stuck (rosy_02)" in capsys.readouterr().out
