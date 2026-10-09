"""CLI 는 파싱과 배선만 한다. 실제 로봇은 Task 14 의 시뮬 계측이 본다."""

import asyncio
from hashlib import sha256
import io
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
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

    # ament installs share/web_common; the D-427 source fallback is shared/web.
    assert args.web_common.name in {"web_common", "web"}
    assert (args.web_common / "shared-assets.json").is_file()
    assert (args.web_common / "tokens.css").is_file()
    assert (args.web_common / "core_ui_logic.js").is_file()


def test_external_console_requires_persistent_task_database(tmp_path):
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--host", "0.0.0.0", "--token", "operator-test"])

    with pytest.raises(SystemExit, match="--tasks-db is required"):
        cli.run_console(args)


def test_console_wires_configured_task_database_into_authenticated_app(tmp_path, monkeypatch):
    robots = _write(tmp_path)
    task_db = tmp_path / "fleet.sqlite3"
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(["console", "--robots", str(robots), "--tasks-db", str(task_db),
                           "--token", "operator-test"])

    cli.run_console(args)

    assert task_db.is_file()
    assert captured["app"].state.task_service.store.path == task_db
    assert captured["app"].state.task_service.robot_ids == {
        "rosy_01", "rosy_02", "rosy_03",
    }


def test_console_mission_api_requires_shared_database_and_named_users(tmp_path):
    robots = _write(tmp_path)
    no_database = cli.parse_args([
        "console", "--robots", str(robots), "--mission-api",
    ])
    with pytest.raises(SystemExit, match="--tasks-db is required with --mission-api"):
        cli.run_console(no_database)

    no_named_users = cli.parse_args([
        "console", "--robots", str(robots), "--tasks-db", str(tmp_path / "fleet.sqlite3"),
        "--mission-api",
    ])
    with pytest.raises(SystemExit, match="--users-file is required with --mission-api"):
        cli.run_console(no_named_users)


def test_console_mission_api_runs_on_development_sessions_without_site_users(tmp_path, monkeypatch):
    # D-548: a development session is the named operator, so no site-users.yaml is needed.
    monkeypatch.setenv("ROSY_DEPLOYMENT", "development")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    cli.run_console(cli.parse_args([
        "console", "--robots", str(_write(tmp_path)), "--tasks-db", str(tmp_path / "fleet.sqlite3"),
        "--mission-api", "--connection-mode", "development",
    ]))
    assert captured["app"].state.mission_service is not None


def test_console_mission_api_persists_candidates_without_enabling_dispatch(
        tmp_path, monkeypatch):
    robots = _write(tmp_path)
    task_db = tmp_path / "fleet.sqlite3"
    users = tmp_path / "site-users.yaml"
    users.write_text(yaml.safe_dump({"users": [{
        "principal_id": "operator-1", "role": "operator",
        "token_sha256": sha256(b"operator-secret").hexdigest(),
    }]}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args([
        "console", "--robots", str(robots), "--users-file", str(users),
        "--tasks-db", str(task_db), "--mission-api",
    ])

    cli.run_console(args)

    app = captured["app"]
    assert app.state.task_service.store.path == task_db
    assert app.state.mission_service.store.path == task_db
    assert app.state.proposal_store.path == task_db
    assert app.state.mission_dispatcher is None

    client = TestClient(app)
    headers = {"Authorization": "Bearer operator-secret"}
    candidate = {
        "source": "gemini_robotics_er2", "model_id": "gemini-robotics-er2",
        "provider_interaction_id": "interaction-1", "provider_call_id": "call-1",
        "instruction": "Move the red block to the green tray",
        "source_observation": {
            "observation_id": "obs-1", "image_sha256": "a" * 64,
            "camera_id": "camera-top", "frame_id": "camera_top_optical",
            "observed_at": "2026-09-29T09:00:00+00:00",
            "calibration_revision": "cal-4", "transform_revision": "tf-9",
        },
        "target_selector": {"label": "red block", "point_yx_1000": [575, 664]},
        "destination_selector": {"label": "green tray", "point_yx_1000": [475, 305]},
    }
    created = client.post("/api/fleet/proposals", headers=headers, json={
        "request_key": "er2-request-1", "workcell_id": "omx_01",
        "instance_id": "omx_01_control", "candidate": candidate,
    })

    assert created.status_code == 200, created.text
    proposal_id = created.json()["proposal"]["proposal_id"]
    assert created.json()["proposal"]["state"] == "PROPOSED"
    assert created.json()["physical_submission"] == "NOT_CONNECTED"
    readback = client.get(f"/api/fleet/proposals/{proposal_id}", headers=headers)
    assert readback.status_code == 200, readback.text
    assert readback.json()["proposal"]["candidate"] == candidate
    unresolved = client.post(f"/api/fleet/proposals/{proposal_id}/resolve", headers=headers)
    assert unresolved.status_code == 503
    assert unresolved.json()["detail"]["code"] == "MISSION_RESOLVER_UNAVAILABLE"


def test_cell_job_stack_tolerance_injects_the_palletizing_compiler(tmp_path, monkeypatch):
    """C4b G5: the Fleet composition root injects the production CellJobCompiler."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "operations/execution/src"))
    robots = _write(tmp_path)
    users = tmp_path / "site-users.yaml"
    users.write_text(yaml.safe_dump({"users": [{
        "principal_id": "operator-1", "role": "operator",
        "token_sha256": sha256(b"operator-secret").hexdigest(),
    }]}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    base = ["console", "--robots", str(robots), "--users-file", str(users),
            "--tasks-db", str(tmp_path / "fleet.sqlite3")]
    with pytest.raises(SystemExit, match="--cell-job-stack-tol-m requires --mission-api"):
        cli.run_console(cli.parse_args(base + ["--cell-job-stack-tol-m", "0.001"]))

    cli.run_console(cli.parse_args(base + ["--mission-api", "--cell-job-stack-tol-m", "0.001"]))

    compiler = captured["app"].state.cell_job_compiler
    assert type(compiler).__name__ == "PalletizingCellJobCompiler"
    assert compiler.tol_m == 0.001
    assert captured["app"].state.mission_dispatcher is None


def test_mission_api_does_not_start_task_dispatcher_for_existing_queued_tasks(
        tmp_path, monkeypatch):
    from fleet.server.task_store import FleetTaskStore

    robots = _write(tmp_path)
    task_db = tmp_path / "fleet.sqlite3"
    users = tmp_path / "site-users.yaml"
    users.write_text(yaml.safe_dump({"users": [{
        "principal_id": "operator-1", "role": "operator",
        "token_sha256": sha256(b"operator-secret").hexdigest(),
    }]}), encoding="utf-8")
    store = FleetTaskStore(task_db)
    task_id = "preexisting-queued-task"
    store.create_task(
        task_id=task_id, robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="operator-1", request_key="preexisting-request",
        request={"x": 1.0, "y": 2.0, "yaw": 0.0}, evidence=None,
    )
    store.enqueue(task_id, priority_class=0, actor_id="operator-1", source="operator")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    dispatcher_started = []

    async def observe_dispatcher(*_args):
        dispatcher_started.append(True)
        await asyncio.Future()

    monkeypatch.setattr("fleet.server.app._task_dispatch_loop", observe_dispatcher)
    args = cli.parse_args([
        "console", "--robots", str(robots), "--users-file", str(users),
        "--tasks-db", str(task_db), "--mission-api",
    ])
    cli.run_console(args)

    with TestClient(captured["app"]) as client:
        assert client.get("/api/fleet/state", headers={
            "Authorization": "Bearer operator-secret",
        }).status_code == 200

    assert dispatcher_started == []
    assert store.get_task(task_id)["status"] == "QUEUED"


def test_console_loads_individual_site_users_for_the_api(tmp_path, monkeypatch):
    robots = _write(tmp_path)
    users = tmp_path / "site-users.yaml"
    users.write_text(yaml.safe_dump({"users": [
        {"principal_id": "viewer-1", "role": "viewer",
         "token_sha256": sha256(b"viewer-token").hexdigest()},
    ]}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(["console", "--robots", str(robots), "--users-file", str(users),
                           "--tasks-db", str(tmp_path / "fleet.sqlite3")])

    cli.run_console(args)

    client = TestClient(captured["app"])
    headers = {"Authorization": "Bearer viewer-token"}
    assert client.get("/api/fleet/state", headers=headers).status_code == 200
    assert client.post("/api/fleet/estop", headers=headers).status_code == 403


def test_console_refuses_individual_site_users_without_durable_audit_database(tmp_path):
    robots = _write(tmp_path)
    users = tmp_path / "site-users.yaml"
    users.write_text(yaml.safe_dump({"users": [{
        "principal_id": "viewer-1", "role": "viewer",
        "token_sha256": sha256(b"viewer-token").hexdigest(),
    }]}), encoding="utf-8")
    args = cli.parse_args(["console", "--robots", str(robots), "--users-file", str(users)])

    with pytest.raises(SystemExit, match="--tasks-db is required with --users-file"):
        cli.run_console(args)


def test_console_loads_source_permissions_and_persistent_sighting_store(tmp_path, monkeypatch):
    robots = _write(tmp_path)
    config = tmp_path / "sightings.yaml"
    config.write_text(yaml.safe_dump({"sources": [{
        "source_id": "ceiling_north", "token_env": "ROSY_TEST_SIGHTING_TOKEN",
        "phone_token_env": "ROSY_TEST_PHONE_TOKEN", "robot_ids": ["rosy_01"],
        "map_id": "site-v1", "calibration_revision": "cal-v3",
        "processor_revision": "aruco-v1", "corner_marker_ids": [30, 31, 32, 33],
        "corner_world_m": [[0, 0], [4, 0], [4, 2], [0, 2]],
        "robot_markers": {"rosy_01": 7},
    }]}), encoding="utf-8")
    monkeypatch.setenv("ROSY_TEST_SIGHTING_TOKEN", "source-secret")
    monkeypatch.setenv("ROSY_TEST_PHONE_TOKEN", "phone-secret")
    monkeypatch.setenv("ROSY_SITE_OPERATOR_TOKEN", "operator-secret")
    captured = {}

    def capture_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", capture_run)
    certificate = tmp_path / "site.crt"
    private_key = tmp_path / "site.key"
    certificate.write_text("certificate", encoding="utf-8")
    private_key.write_text("private-key", encoding="utf-8")
    args = cli.parse_args(["console", "--robots", str(robots), "--token-env",
                           "ROSY_SITE_OPERATOR_TOKEN",
                           "--sightings-config", str(config), "--sightings-db",
                           str(tmp_path / "fleet.sqlite3"), "--tls-cert", str(certificate),
                           "--tls-key", str(private_key)])

    cli.run_console(args)

    client = TestClient(captured["app"])
    accepted = client.post(
        "/api/fleet/sightings",
        json={"robot_id": "rosy_01", "x": 1.0, "y": 1.0, "yaw": 0.0,
              "captured_at": time.time(), "seq": 5, "map_id": "site-v1",
              "calibration_revision": "cal-v3", "processor_revision": "aruco-v1",
              "quality": None, "corner_marker_ids": [30, 31, 32, 33]},
        headers={"Authorization": "Bearer source-secret"},
    )
    assert accepted.status_code == 200, accepted.text
    readback = client.get("/api/fleet/sightings",
                          headers={"Authorization": "Bearer operator-secret"})
    assert readback.status_code == 200
    assert readback.json()["sightings"][0]["seq"] == 5
    assert captured["kwargs"]["ssl_certfile"] == str(certificate)
    assert captured["kwargs"]["ssl_keyfile"] == str(private_key)
    assert (tmp_path / "fleet.sqlite3").is_file()


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


# --- D-361 robot enrollment wiring ---------------------------------------------------

def _key_file(tmp_path):
    import base64

    path = tmp_path / "robot_credential_key"
    path.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
    return path


def _sighting_config(tmp_path, robot_ids):
    config = tmp_path / "sightings.yaml"
    config.write_text(yaml.safe_dump({"sources": [{
        "source_id": "ceiling_north", "token_env": "ROSY_TEST_SIGHTING_TOKEN",
        "robot_ids": robot_ids, "map_id": "site-v1", "calibration_revision": "cal-v3",
        "corner_marker_ids": [30, 31, 32, 33],
    }]}), encoding="utf-8")
    return config


def test_console_without_robots_file_needs_the_enrollment_key(tmp_path):
    args = cli.parse_args(["console", "--tasks-db", str(tmp_path / "fleet.sqlite3")])
    with pytest.raises(SystemExit, match="--robots is required"):
        cli.run_console(args)
    args = cli.parse_args(["console", "--robot-credential-key-file", str(_key_file(tmp_path))])
    with pytest.raises(SystemExit, match="--tasks-db is required"):
        cli.run_console(args)


def test_console_with_enrollment_key_starts_without_robots_file(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(["console", "--tasks-db", str(tmp_path / "fleet.sqlite3"),
                           "--robot-credential-key-file", str(_key_file(tmp_path)),
                           "--token", "operator-test"])
    cli.run_console(args)
    client = TestClient(captured["app"])
    listed = client.get("/api/fleet/enrollment/robots",
                        headers={"Authorization": "Bearer operator-test"})
    assert listed.status_code == 200 and listed.json()["available"] is True


def test_console_with_a_broken_key_still_starts(tmp_path, monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    broken = tmp_path / "robot_credential_key"
    broken.write_bytes(bytes(range(32)))
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--tasks-db", str(tmp_path / "fleet.sqlite3"),
                           "--robot-credential-key-file", str(broken), "--token", "operator-test"])
    cli.run_console(args)
    client = TestClient(captured["app"])
    headers = {"Authorization": "Bearer operator-test"}
    assert client.get("/api/fleet/enrollment/robots", headers=headers).json()["available"] is False
    assert len(client.get("/api/fleet/state", headers=headers).json()["robots"]) == 3
    assert "robot enrollment unavailable" in capsys.readouterr().err


def test_sighting_mapping_to_an_unenrolled_robot_warns_instead_of_refusing(tmp_path, monkeypatch,
                                                                           capsys):
    from fleet.server.enrollment_store import EnrollmentStore

    database = tmp_path / "fleet.sqlite3"
    EnrollmentStore(database).audit(action="unenroll", outcome="removed", principal_id="alice",
                                    target="rosy_09")
    monkeypatch.setenv("ROSY_TEST_SIGHTING_TOKEN", "source-secret")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)), "--tasks-db", str(database),
                           "--robot-credential-key-file", str(_key_file(tmp_path)),
                           "--token", "operator-test",
                           "--sightings-config", str(_sighting_config(tmp_path,
                                                                      ["rosy_01", "rosy_09"]))])
    cli.run_console(args)
    assert "rosy_09" in capsys.readouterr().err

    args.sightings_config = _sighting_config(tmp_path, ["rosy_01", "rosy_77"])
    with pytest.raises(SystemExit, match="unknown robot target"):
        cli.run_console(args)


def _pairing_files(tmp_path, monkeypatch):
    from test_camera_peer_routes import certificates

    site_ca, served_chain, private_key = certificates('fixture-site.local', with_key=True)

    robots = _write(tmp_path)
    config = tmp_path / "site-cameras.yaml"
    config.write_text(yaml.safe_dump({"sources": [{
        "source_id": "ceiling_north", "token_env": "ROSY_TEST_SIGHTING_TOKEN",
        "credential": "paired", "robot_ids": ["rosy_01"], "map_id": "site-v1",
        "calibration_revision": "cal-v3", "corner_marker_ids": [30, 31, 32, 33],
    }]}), encoding="utf-8")
    (tmp_path / "site.crt").write_text(served_chain, encoding="utf-8")
    (tmp_path / "site.key").write_text(private_key, encoding="utf-8")
    (tmp_path / "site-ca.crt").write_text(site_ca, encoding="utf-8")
    (tmp_path / "leaf-only.crt").write_text(served_chain.split('-----END CERTIFICATE-----', 1)[0]
                                           + '-----END CERTIFICATE-----\n', encoding="utf-8")
    monkeypatch.setenv("ROSY_TEST_SIGHTING_TOKEN", "source-secret")
    monkeypatch.setenv("ROSY_SITE_OPERATOR_TOKEN", "operator-secret")
    monkeypatch.setenv("ROSY_TEST_PAIRING_SYNC", "sync-" + "secret-1")
    return ["console", "--robots", str(robots), "--token-env", "ROSY_SITE_OPERATOR_TOKEN",
            "--sightings-config", str(config), "--tasks-db", str(tmp_path / "fleet.sqlite3")]


def test_console_wires_d341_pairing_only_with_tls(tmp_path, monkeypatch):
    from core_common.protocol import pairing

    base = _pairing_files(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    cli.run_console(cli.parse_args(base + [
        "--tls-cert", str(tmp_path / "site.crt"), "--tls-key", str(tmp_path / "site.key"),
        "--pairing-ca", str(tmp_path / "site-ca.crt"), "--pairing-tls-host", "fixture-site.local",
        "--pairing-sync-token-env", "ROSY_TEST_PAIRING_SYNC"]))

    client = TestClient(captured["app"])
    listing = client.get("/api/fleet/pairing/v1/credentials", params={"role": "overhead-camera"},
                         headers={"Authorization": "Bearer sync-" + "secret-1"})
    assert listing.status_code == 200 and listing.json()["credentials"] == []
    pending = client.get("/api/fleet/pairing/v1/pending",
                         headers={"Authorization": "Bearer operator-secret"}).json()
    assert pending["paired_sources"] == [{"source_id": "ceiling_north", "has_credential": False}]
    assert pending["site_ca_fingerprint"] == pairing.site_fingerprint(
        (tmp_path / "site-ca.crt").read_text(encoding="utf-8"))
    assert pairing.der_sha256((tmp_path / "leaf-only.crt").read_text(encoding="utf-8")) == pairing.der_sha256(
        (tmp_path / "site.crt").read_text(encoding="utf-8"))


@pytest.mark.parametrize("extra, message", [
    (["--pairing-ca", "{ca}", "--pairing-tls-host", "fixture-site.local"], "--tls-cert"),
    (["--tls-cert", "{crt}", "--tls-key", "{key}", "--pairing-ca", "{leaf}",
      "--pairing-tls-host", "fixture-site.local"], "CA"),
    (["--tls-cert", "{crt}", "--tls-key", "{key}", "--pairing-ca", "{ca}"], "--pairing-tls-host"),
    (["--pairing-sync-token-env", "ROSY_TEST_PAIRING_SYNC"], "--pairing-ca"),
])
def test_console_refuses_incomplete_d341_pairing(tmp_path, monkeypatch, extra, message):
    base = _pairing_files(tmp_path, monkeypatch)
    names = {"ca": "site-ca.crt", "crt": "site.crt", "key": "site.key", "leaf": "leaf-only.crt"}
    extra = [item.format(**{key: str(tmp_path / value) for key, value in names.items()})
             for item in extra]
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)
    with pytest.raises(SystemExit, match=message):
        cli.run_console(cli.parse_args(base + extra))


def test_console_starts_the_localization_service_by_default_with_the_overhead_cue_off(
        tmp_path, monkeypatch):
    """D-395 P2-6: the service is on unless switched off; the D-257 sighting cue is off."""
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    cli.run_console(cli.parse_args(["console", "--robots", str(_write(tmp_path))]))

    service = captured["app"].state.localization_service
    assert service is not None and service.overhead_cue is False
    assert len(service._squares) == 2          # the repo's map_v2_fleet lane_rules.yaml


def test_console_localization_switches(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    robots = str(_write(tmp_path))
    cli.run_console(cli.parse_args(["console", "--robots", robots, "--no-localization-service"]))
    assert captured["app"].state.localization_service is None

    rules = tmp_path / "rules.yaml"
    rules.write_text("reference_squares:\n  - {centre: [0.5, 0.5], heading_axis_deg: 0}\n",
                     encoding="utf-8")
    cli.run_console(cli.parse_args(["console", "--robots", robots, "--localization-overhead-cue",
                                    "--localization-lane-rules", str(rules)]))
    service = captured["app"].state.localization_service
    assert service.overhead_cue is True and service._squares == ((0.5, 0.5),)


@pytest.mark.parametrize(("deployment", "mode", "expected"), [
    ("", "paired", "paired"),
    ("development", "paired", "paired"),
    ("", "development", "paired"),
    ("development", "development", "development"),
])
def test_console_development_mode_needs_both_the_flag_and_the_deployment(
        tmp_path, monkeypatch, deployment, mode, expected):
    # D-473 1: a missing or mismatched setting never falls back to development mode.
    monkeypatch.setenv("ROSY_DEPLOYMENT", deployment)
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--tasks-db", str(tmp_path / "fleet.sqlite3"),
                           "--token", "operator-test", "--connection-mode", mode])

    cli.run_console(args)

    client = TestClient(captured["app"], client=("192.168.1.50", 50000),
                        base_url="http://192.168.1.10:8090")
    assert client.get("/api/fleet/auth/connection").json() == {"mode": expected, "password_login": False}
    issued = client.post("/api/fleet/auth/development-session")
    assert issued.status_code == (201 if expected == "development" else 403)


def test_console_connection_mode_defaults_to_paired(tmp_path):
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path))])

    assert args.connection_mode == "paired"


def test_console_refuses_an_unknown_connection_mode(tmp_path):
    with pytest.raises(SystemExit):
        cli.parse_args(["console", "--robots", str(_write(tmp_path)), "--connection-mode", "open"])


def test_console_development_mode_requires_the_task_database(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "development")
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--connection-mode", "development"])

    with pytest.raises(SystemExit, match="--tasks-db is required with --connection-mode development"):
        cli.run_console(args)
