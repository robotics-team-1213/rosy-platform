"""관제 HTTP 표면 — 경로, 상태 코드, 토큰 가드, 자산 allowlist."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from core_common.intent import MAX_STEPS, verbs
from core_common.protocol.vision_preview import VisionLeaseSigner

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

GRID = {"map_id": "occupancy:abc", "width": 1, "height": 1, "resolution": 0.05,
        "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": [0]}


def _client(*robots: FakeRobot, token=None, web_common=None) -> TestClient:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, list(robots))
    return TestClient(create_app(console, console_token=token, web_common=web_common))


def test_health_endpoint_reports_liveness_without_robot_or_auth_data():
    response = _client(FakeRobot("rosy_01"), token="operator-secret").get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "robot" not in response.text and "token" not in response.text


def test_vision_lease_is_source_scoped_and_fleet_returns_no_frame_bytes():
    robots = [FakeRobot("rosy_01")]
    console = FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")], robots)
    client = TestClient(create_app(
        console, vision_lease_secret="v" * 32, vision_sources=("ceiling-north",)))

    response = client.post("/api/fleet/vision/lease", json={"source_id": "ceiling-north"})
    rejected = client.post("/api/fleet/vision/lease", json={"source_id": "other"})

    assert response.status_code == 200
    body = response.json()
    assert body["frame_path"] == "/api/vision/sources/ceiling-north/frame"
    assert body["expires_in_s"] == 60
    assert VisionLeaseSigner("v" * 32).verify(
        body["lease"], source_id="ceiling-north")["scope"] == "frame:read"
    assert "jpeg" not in body and "image" not in body
    assert rejected.status_code == 404


def test_lan_camera_proxy_grant_only_opens_preview_routes(tmp_path):
    console = FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
        [FakeRobot("rosy_01")],
    )
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=("rosy_01",))
    client = TestClient(create_app(
        console, task_service=tasks,
        site_users={sha256(b"viewer-token").hexdigest(): {
            "principal_id": "viewer", "role": "viewer"}},
        vision_lease_secret="v" * 32, vision_sources=("ceiling-north",),
        lan_camera_proxy=True,
    ))
    proxy_grant = {"X-Rosy-Lan-Camera": "1"}
    lease_path = "/api/fleet/vision/lease"
    source_path = "/api/fleet/vision/sources"

    assert client.get(source_path).status_code == 401
    assert client.post(lease_path, json={"source_id": "ceiling-north"}).status_code == 401
    assert client.get(source_path, headers=proxy_grant).json() == {"sources": ["ceiling-north"]}
    issued = client.post(lease_path, json={"source_id": "ceiling-north"}, headers=proxy_grant)
    assert issued.status_code == 200
    assert VisionLeaseSigner("v" * 32).verify(
        issued.json()["lease"], source_id="ceiling-north")["sub"] == "lan-camera"
    assert client.get("/api/fleet/state", headers=proxy_grant).status_code == 401
    assert client.post("/api/fleet/estop", headers=proxy_grant).status_code == 401
    assert client.get(source_path, headers={**proxy_grant,
                                            "Authorization": "Bearer wrong"}).status_code == 401
    assert _client(FakeRobot("rosy_01"), token="secret").get(
        source_path, headers=proxy_grant).status_code == 401


def test_vision_lease_accepts_only_bounded_preview_rectification():
    client = TestClient(create_app(
        FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
                     [FakeRobot("rosy_01")]),
        vision_lease_secret="v" * 32, vision_sources=("ceiling-north",)))
    profile = {
        "fx": 1.2, "fy": 1.2, "cx": 0.5, "cy": 0.5,
        "k1": -0.18, "k2": 0.03, "p1": 0.0, "p2": 0.0, "k3": 0.0,
        "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "output_aspect": 1.0,
    }

    issued = client.post("/api/fleet/vision/lease", json={
        "source_id": "ceiling-north", "rectification": profile,
    })
    rejected = client.post("/api/fleet/vision/lease", json={
        "source_id": "ceiling-north", "rectification": {"k1": 999},
    })

    assert issued.status_code == 200
    assert VisionLeaseSigner("v" * 32).verify(
        issued.json()["lease"], source_id="ceiling-north")["rectification"] == profile
    assert rejected.status_code == 422


def test_vision_lease_endpoint_fails_closed_when_preview_is_not_configured():
    client = _client(FakeRobot("rosy_01"))

    response = client.post("/api/fleet/vision/lease", json={"source_id": "ceiling-north"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "VISION_PREVIEW_DISABLED"


def test_preview_asset_is_served_from_the_allowlist_and_csp_allows_its_blob_frames():
    client = _client(FakeRobot("rosy_01"))

    asset = client.get("/console/assets/vision-view.js")
    page = client.get("/console")

    assert asset.status_code == 200
    assert "createVisionView" in asset.text
    assert "img-src 'self' data: blob:" in page.headers["content-security-policy"]


def test_preview_secret_cannot_be_reused_as_a_named_user_credential(tmp_path):
    secret = "v" * 64
    console = FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
        [FakeRobot("rosy_01")],
    )
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=("rosy_01",))
    users = {sha256(secret.encode("utf-8")).hexdigest():
             {"principal_id": "viewer", "role": "viewer"}}

    with pytest.raises(ValueError, match="vision preview secret must differ from site user"):
        create_app(console, site_users=users, task_service=tasks, vision_lease_secret=secret)


def test_goal_openapi_contract_exposes_only_domain_intent_fields():
    app = create_app(FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")],
        [FakeRobot("rosy_01")],
    ))

    operation = app.openapi()["paths"]["/api/fleet/robots/{robot_id}/goal"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"] == "#/components/schemas/GoalRequest"

    goal_schema = app.openapi()["components"]["schemas"]["GoalRequest"]
    assert goal_schema["required"] == ["x", "y"]
    assert set(goal_schema["properties"]) == {"x", "y", "yaw"}
    assert goal_schema["additionalProperties"] is False
    assert all(goal_schema["properties"][name]["type"] == "number"
               for name in ("x", "y", "yaw"))


def test_camera_fault_ir_selection_is_forwarded_only_as_explicit_operator_intent():
    robot = FakeRobot("rosy_01")
    client = _client(robot)

    selected = client.post("/api/fleet/robots/rosy_01/line-follow", json={"mode": "IR_LINE"})
    invalid = client.post("/api/fleet/robots/rosy_01/line-follow", json={"mode": "CAMERA_LINE"})

    assert selected.status_code == 200
    assert selected.json()["result"] == {"mode": "IR_LINE", "state": "WAITING"}
    assert ("line_follow_mode", "IR_LINE") in robot.calls
    assert invalid.status_code == 400
    assert sum(call[0] == "line_follow_mode" for call in robot.calls) == 1


def test_do_openapi_contract_matches_intent_verbs_and_bounded_sequences():
    app = create_app(FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")],
        [FakeRobot("rosy_01")],
    ))

    operation = app.openapi()["paths"]["/api/fleet/do"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    single_step, sequence = schema["oneOf"]
    step_schemas = single_step["oneOf"]

    assert {item["properties"]["do"]["const"] for item in step_schemas} == set(verbs())
    assert all(item["additionalProperties"] is False for item in step_schemas)
    navigate = next(item for item in step_schemas
                    if item["properties"]["do"]["const"] == "navigate")
    assert navigate["properties"]["x"]["type"] == "number"
    assert navigate["properties"]["waypoint"]["type"] == "string"
    assert "priority_class" not in navigate["properties"]

    steps = sequence["properties"]["steps"]
    assert sequence["required"] == ["steps"]
    assert sequence["additionalProperties"] is False
    assert steps["minItems"] == 1
    assert steps["maxItems"] == MAX_STEPS
    assert steps["items"] == single_step


def test_do_translates_a_goal_and_rejects_a_ros_word():
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    client = _client(robot)
    sent = client.post("/api/fleet/do", json={
        "do": "navigate", "robot": "rosy_01", "x": 1.0, "y": 2.0, "yaw": 0.0,
    })
    assert sent.status_code == 200, sent.text
    assert sent.json()["steps"][0]["path"] == "/api/v1/navigation/goal"
    refused = client.post("/api/fleet/do", json={"do": "navigate", "x": 0, "y": 0, "twist": {}})
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "FORBIDDEN"


def test_do_rejects_client_priority_and_boolean_goal_without_dispatch():
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    client = _client(robot)

    priority = client.post("/api/fleet/do", json={
        "do": "navigate", "robot": "rosy_01", "x": 1.0, "y": 2.0,
        "priority_class": 0,
    })
    boolean_goal = client.post("/api/fleet/do", json={
        "do": "navigate", "robot": "rosy_01", "x": True, "y": 2.0,
    })

    assert priority.status_code == 400
    assert priority.json()["detail"]["code"] == "UNKNOWN_FIELD"
    assert boolean_goal.status_code == 400
    assert boolean_goal.json()["detail"]["code"] == "INVALID_NUMBER"
    assert not any(call[0] == "navigation_goal" for call in robot.calls)


def test_do_rejects_mistyped_motion_values_before_robot_dispatch():
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    client = _client(robot)

    response = client.post("/api/fleet/do", json={
        "do": "move", "robot": "rosy_01", "linear": "fast", "angular": 0.0,
    })

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_NUMBER"
    assert not robot.calls


def test_state_lists_the_roster():
    client = _client(FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"}),
                     FakeRobot("rosy_02", state={"robot_id": "rosy_02", "mode": "NAVIGATION"}))
    body = client.get("/api/fleet/state").json()
    assert body["fleet"]["total"] == 2
    assert [r["robot_id"] for r in body["robots"]] == ["rosy_01", "rosy_02"]


def test_map_is_404_when_no_robot_serves_one():
    blind = FakeRobot("rosy_01")
    blind.map_error = ConnectionError("down")
    assert _client(blind).get("/api/fleet/map").status_code == 404


def test_map_is_served_when_a_robot_has_one():
    assert _client(FakeRobot("rosy_01", map=GRID)).get("/api/fleet/map").json()["map_id"] \
        == "occupancy:abc"


def test_goal_to_an_unknown_robot_is_404_not_502():
    """오타는 사이트 쪽 잘못이다. 502 로 내면 로봇이 거절한 것처럼 읽힌다."""
    resp = _client(FakeRobot("rosy_01")).post("/api/fleet/robots/rosy_99/goal",
                                              json={"x": 0.0, "y": 0.0})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "UNKNOWN_ROBOT"


@pytest.mark.parametrize("body", [
    {"x": 1.0, "y": 2.0, "priority_class": 0},
    {"x": 1.0, "y": 2.0, "source": "policy"},
    {"x": True, "y": 2.0},
])
def test_goal_rejects_non_intent_dispatch_fields_and_invalid_numbers(body):
    robot = FakeRobot("rosy_01")
    response = _client(robot).post("/api/fleet/robots/rosy_01/goal", json=body)

    assert response.status_code == 422
    assert not any(call[0] == "navigation_goal" for call in robot.calls)


def test_a_goal_the_robot_refuses_comes_back_as_502_with_the_robot_code():
    robot = FakeRobot("rosy_01")

    async def refuse(x, y, yaw):
        raise RobotApiError("rosy_01", 409, "MODE_CONFLICT", "not in NAVIGATION")

    robot.navigation_goal = refuse
    resp = _client(robot).post("/api/fleet/robots/rosy_01/goal", json={"x": 1.0, "y": 0.0})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "MODE_CONFLICT"
    assert resp.json()["detail"]["robot_id"] == "rosy_01"


def test_estop_is_200_even_when_one_robot_refuses():
    """부분 실패를 5xx 로 접으면 어느 대가 섰는지 화면이 알 수 없다."""
    good = FakeRobot("rosy_01")
    bad = FakeRobot("rosy_02")

    async def blow_up():
        raise ConnectionError("gone")

    bad.estop = blow_up
    resp = _client(good, bad).post("/api/fleet/estop")
    assert resp.status_code == 200
    assert resp.json()["stopped"] == 1


@pytest.mark.parametrize("path", ["/api/fleet/state", "/api/fleet/estop"])
def test_console_token_guards_the_site_api(path):
    """이 포트는 현장의 모든 로봇을 움직인다 — 토큰을 켜면 전부 막힌다."""
    client = _client(FakeRobot("rosy_01"), token="secret")
    method = client.get if path.endswith("state") else client.post
    assert method(path).status_code == 401
    assert method(path, headers={"Authorization": "Bearer secret"}).status_code == 200


def test_viewer_can_read_fleet_state_but_cannot_issue_robot_commands(tmp_path):
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")],
                           [robot])
    task_service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    client = TestClient(create_app(
        console,
        task_service=task_service,
        site_users={
            sha256(b"viewer-token").hexdigest(): {"principal_id": "alice", "role": "viewer"},
            sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
            sha256(b"policy-token").hexdigest(): {
                "principal_id": "carol", "role": "policy-admin",
            },
        },
    ))

    viewer = {"Authorization": "Bearer viewer-token"}
    operator = {"Authorization": "Bearer operator-token"}
    policy_admin = {"Authorization": "Bearer policy-token"}
    assert client.get("/api/fleet/state").status_code == 401
    assert client.get("/api/fleet/state", headers={
        "Authorization": "Bearer unlisted-token",
    }).status_code == 401
    assert client.get("/api/fleet/state", headers=viewer).status_code == 200
    assert client.get("/api/fleet/state", headers=policy_admin).status_code == 200
    denied_goal = client.post(
        "/api/fleet/robots/rosy_01/goal", json={"x": 1.0, "y": 2.0},
        headers={**viewer, "Idempotency-Key": "viewer-must-not-move"},
    )
    assert denied_goal.status_code == 403
    denied = client.post("/api/fleet/estop", headers=viewer)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "FORBIDDEN"
    assert client.post("/api/fleet/estop", headers=policy_admin).status_code == 403
    assert client.post("/api/fleet/estop", headers=operator).status_code == 200
    assert not any(call[0] == "navigation_goal" for call in robot.calls)
    audits = [row for row in task_service.store.api_audit() if row["event_type"] == "RESULT"]
    assert [(row["principal_id"], row["status_code"]) for row in audits[:2]] == [
        ("bob", 200), ("carol", 403),
    ]
    assert audits[2]["principal_id"] == "alice" and audits[2]["status_code"] == 403


def test_site_session_returns_only_the_authenticated_principal_and_role(tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")],
                           [FakeRobot("rosy_01")])
    task_service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    client = TestClient(create_app(
        console, task_service=task_service,
        site_users={sha256(b"viewer-token").hexdigest(): {
            "principal_id": "alice", "role": "viewer",
        }},
    ))

    assert client.get("/api/fleet/session").status_code == 401
    response = client.get("/api/fleet/session",
                          headers={"Authorization": "Bearer viewer-token"})

    assert response.status_code == 200
    assert response.json() == {"principal_id": "alice", "role": "viewer"}


def test_per_user_authorization_requires_persistent_audit_storage():
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")],
                           [FakeRobot("rosy_01")])
    with pytest.raises(ValueError, match="persistent task/audit storage"):
        create_app(console, site_users={
            sha256(b"viewer-token").hexdigest(): {"principal_id": "alice", "role": "viewer"},
        })


@pytest.mark.parametrize("shared_secret, pairing_token", [
    ("robot-rest", None),
    ("agent-pairing", "agent-pairing"),
])
def test_site_user_credentials_cannot_be_reused_for_robot_services(
        tmp_path, shared_secret, pairing_token):
    endpoint = RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest",
                             fleet_pairing_token=pairing_token)
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    task_service = FleetTaskService(
        FleetTaskStore(tmp_path / f"{sha256(shared_secret.encode()).hexdigest()}.sqlite3"),
        robot_ids={"rosy_01"})

    with pytest.raises(ValueError, match="site user credentials must differ from robot credentials"):
        create_app(console, task_service=task_service, site_users={
            sha256(shared_secret.encode()).hexdigest(): {
                "principal_id": "user-1", "role": "operator",
            },
        })


def test_authenticated_estop_proceeds_and_logs_when_audit_storage_is_unavailable(
        tmp_path, monkeypatch, caplog):
    robot = FakeRobot("rosy_01")
    task_store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    task_service = FleetTaskService(task_store, robot_ids={"rosy_01"})
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot])
    client = TestClient(create_app(
        console, task_service=task_service,
        site_users={sha256(b"operator-token").hexdigest(): {
            "principal_id": "operator-1", "role": "operator",
        }},
    ))

    def fail_audit(**_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(task_store, "begin_api_audit", fail_audit)
    response = client.post("/api/fleet/estop", headers={"Authorization": "Bearer operator-token"})

    assert response.status_code == 200
    assert ("estop",) in robot.calls
    assert "operator-1" in caplog.text and "audit" in caplog.text.lower()


def test_non_estop_mutation_remains_blocked_when_audit_storage_is_unavailable(
        tmp_path, monkeypatch):
    robot = FakeRobot("rosy_01")
    task_store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    task_service = FleetTaskService(task_store, robot_ids={"rosy_01"})
    client = TestClient(create_app(
        FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot]),
        task_service=task_service,
        site_users={sha256(b"operator-token").hexdigest(): {
            "principal_id": "operator-1", "role": "operator",
        }},
    ))

    def fail_audit(**_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(task_store, "begin_api_audit", fail_audit)
    response = client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 2},
                           headers={"Authorization": "Bearer operator-token",
                                    "Idempotency-Key": "audit-failure-goal"})

    assert response.status_code == 503
    assert not any(call[0] == "navigation_goal" for call in robot.calls)


def test_estop_fanout_survives_dispatch_latch_and_queue_storage_failures(tmp_path, monkeypatch,
                                                                          caplog):
    robot = FakeRobot("rosy_01")
    task_service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    client = TestClient(create_app(
        FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot]),
        task_service=task_service,
        site_users={sha256(b"operator-token").hexdigest(): {
            "principal_id": "operator-1", "role": "operator",
        }},
    ))

    def fail_store(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(task_service.store, "trip_stop_latch", fail_store)
    monkeypatch.setattr(task_service, "cancel_all_queued", fail_store)
    response = client.post("/api/fleet/estop", headers={"Authorization": "Bearer operator-token"})

    assert response.status_code == 200
    assert ("estop",) in robot.calls
    assert "dispatch latch unavailable" in caplog.text
    assert "queue cleanup unavailable" in caplog.text


def test_console_page_and_its_assets_are_served():
    client = _client(FakeRobot("rosy_01"))
    page = client.get("/console")
    assert page.status_code == 200
    assert "Rosy Fleet" in page.text  # D-487
    assert "Rosy Console" not in page.text
    assert "ROSY FLEET" not in page.text
    assert "SITE CONSOLE" not in page.text
    script = (Path(__file__).resolve().parents[1] / "fleet" / "server" / "web" / "console.js").read_text(encoding="utf-8")
    assert 'el("fleet-name").textContent = snapshot.fleet.name || "사이트";' in script
    assert client.get("/console/assets/console.js").status_code == 200
    assert client.get("/console/assets/authorization.js").status_code == 200
    assert client.get("/console/assets/styles.css").status_code == 200
    assert 'id="user-role"' in page.text
    assert 'href="/common/tokens.css"' in page.text


def test_install_page_and_its_entry_are_served():
    """D-410 — 설치·보정 화면은 같은 CSP·자산 규칙 아래 서빙된다."""
    client = _client(FakeRobot("rosy_01"))
    page = client.get("/console/install")
    assert page.status_code == 200 and "설치·보정" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/console/assets/install.js").status_code == 200
    assert client.get("/console/assets/peer-picker.js").status_code == 200
    assert 'id="peer-picker"' in page.text and 'id="peer-retry"' in page.text
    assert 'id="camera-install-heading"' in page.text
    assert 'id="robot-enrollment"' in page.text
    # 운용 화면은 이제 등록·보정 마크업을 들고 있지 않다 — 링크만 남는다.
    ops = client.get("/console").text
    assert 'id="robot-enrollment"' not in ops
    assert 'id="vision-adjustments"' not in ops
    assert 'href="/console/install"' in ops


def test_the_tokens_copy_is_gone_from_the_allowlist():
    """D-129 — 사본이 없으니 allowlist 도 이름을 잃는다. 부활은 위반이다."""
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/console/assets/tokens.css").status_code == 404


def test_common_assets_are_404_until_configured():
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/common/tokens.css").status_code == 404
    assert client.get("/common/core_ui_logic.js").status_code == 404


def test_common_assets_serve_only_the_configured_allowlist(tmp_path):
    tokens = tmp_path / "tokens.css"
    tokens.write_text(":root { --probe: #000000; }", encoding="utf-8")
    logic = tmp_path / "core_ui_logic.js"
    logic.write_text("export class HeadlessState {}", encoding="utf-8")
    client = _client(FakeRobot("rosy_01"), web_common=tmp_path)
    resp = client.get("/common/tokens.css")
    assert resp.status_code == 200
    assert resp.text == ":root { --probe: #000000; }"
    assert client.get("/common/core_ui_logic.js").status_code == 200
    assert client.get("/common/secret.txt").status_code == 404
    assert client.get("/ui/tokens.css").text == resp.text


def test_asset_allowlist_refuses_anything_it_does_not_name():
    """allowlist 가 경로 순회를 막는 유일한 방어다 — 디렉터리 스캔으로 바꾸지 않는다."""
    client = _client(FakeRobot("rosy_01"))
    assert client.get("/console/assets/../console.py").status_code == 404
    assert client.get("/console/assets/secrets.env").status_code == 404


def test_common_allowlist_is_the_web_common_manifest():
    """The shared hold ticker is in web_common's manifest, so Fleet serves it too."""
    from fleet.cli import default_web_common

    client = _client(FakeRobot("rosy_01"), web_common=default_web_common())
    ticker = client.get("/common/hold-ticker.js")
    assert ticker.status_code == 200
    assert ticker.headers["content-type"].startswith("text/javascript")
    assert client.get("/common/shared-assets.json").status_code == 404
    assert client.get("/common/CMakeLists.txt").status_code == 404


def test_every_console_module_import_is_served():
    """A console ES module that 404s takes the whole console down, e-stop included."""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
    client = _client(FakeRobot("rosy_01"))
    imported = set()
    for script in web.glob("*.js"):
        imported |= set(re.findall(r'from\s+"\./([\w.-]+\.js)"', script.read_text(encoding="utf-8")))
    assert "enrollment.js" in imported
    for name in sorted(imported | {"console.js"}):
        assert client.get(f"/console/assets/{name}").status_code == 200, name


def test_the_localization_service_runs_in_the_app_lifespan_and_feeds_the_badge():
    """D-395 P2-6: the loop starts and stops with the app like the other background loops."""
    import asyncio

    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "pose": {"x": 0, "y": 0, "yaw": 0},
                                     "localization": {"state": "CANDIDATES", "pose_frame": "odom"}})
    console = FleetConsole([RobotEndpoint("rosy_01", "http://a:8080", "t")], [robot])

    class Service:
        runs = 0
        cancelled = False

        def view(self, robot_id):
            return {"needs_human": True}

        async def run(self):
            Service.runs += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                Service.cancelled = True
                raise

    with TestClient(create_app(console, localization_service=Service())) as client:
        row = client.get("/api/fleet/state").json()["robots"][0]
        assert Service.runs == 1
    assert Service.cancelled is True
    assert row["localization"]["label"] == "위치 확인 필요"
    assert row["localization"]["state"] == "CANDIDATES" and row["localization"]["trusted"] is False
