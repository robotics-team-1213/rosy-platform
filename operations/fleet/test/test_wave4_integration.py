"""Wave 4 ROSY integration tests: outbound loaded port events, cell-site recognition API,
dual-mode cell-plan batch admit, and dynamic bridge_real_fleet robot roster.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from applications.world.bridge_real_fleet import CANONICAL_FLEET_ROBOTS, fleet_state_to_world_state
from core_common.protocol.port_events import PortEvent, event_id
from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.recognition.workcell_observation_routes import install_workcell_observation_routes
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from rosy_account.principal import SitePrincipal
from tools.sim.bay_departure_sim import build_world_261026_site_map

T = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
CELL = "cell-supply"
VIEW = {"Authorization": "Bearer viewer"}
SVC = {"Authorization": "Bearer harbor-svc"}
OP = {"Authorization": "Bearer operator"}


def _recognition_app(tmp_path, *, web_common=None):
    principals = {
        hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(p, r)
        for t, p, r in (
            ("viewer", "viewer-1", "viewer"),
            ("harbor-svc", "harbor-service", "service"),
            ("operator", "console-human", "operator"),
        )
    }
    auth = build_authorize(None, principals, None)
    require_viewer, _, require_named_operator, _ = build_role_guards(auth, principals)

    class Observations:
        def uses_token(self, token):
            return token in {"cam-token", "cell-token"}

        def authorize(self, source_id, token):
            if source_id != "arm_a" or token != "cell-token":
                raise PermissionError

        def authorize_workcell(self, workcell_id, token):
            if workcell_id != CELL:
                raise KeyError(workcell_id)
            if token != "cell-token":
                raise PermissionError

        def snapshot(self):
            return {"read_only": True, "physical_acceptance": False, "workcells": []}

    app = FastAPI()
    app.state.web_common = web_common
    app.state.control_unit = SimpleNamespace(
        unit=SimpleNamespace(unit_id="cell-a", parent="R"),
        topology=SimpleNamespace(units={}),
        peer=None,
    )
    install_workcell_observation_routes(
        app,
        Observations(),
        require_viewer,
        require_named_operator=require_named_operator,
        task_service=SimpleNamespace(store=SimpleNamespace(path=tmp_path / "fleet.sqlite3")),
        authorize=auth,
    )
    return TestClient(app)


def _sample_recognition_snapshot(**overrides):
    doc = {
        "schema": "rosy.cell-site-recognition.v1",
        "snapshot_id": "snap-wave4-1",
        "observed_at": "2026-11-25T02:00:00Z",
        "source_id": "omx_overhead",
        "calibration_revision": "cal-1",
        "site_map_revision": 1,
        "sites": [
            {
                "site_ref": "yard-r1-c1-l1",
                "state": "OCCUPIED",
                "object_class": "orange",
                "object_ref_read": "CNTR-W4",
                "confidence": 0.94,
            },
            {
                "site_ref": "stand-r1-c1-l1",
                "state": "EMPTY",
                "object_class": None,
                "object_ref_read": None,
                "confidence": 0.91,
            },
        ],
    }
    doc.update(overrides)
    return doc


def test_wave4_outbound_loaded_port_event_contract_and_ingest_roundtrip(tmp_path):
    ev = PortEvent(
        event_id=event_id(CELL, "obs-load-1", "container.loaded_for_outbound"),
        kind="container.loaded_for_outbound",
        observation_ref="obs-load-1",
        object_ref="CNTR-OUT-1",
        vehicle_id="rosy_46",
        identity="observed",
        observed_at=T,
    )
    assert ev.matches(CELL)

    for bad in (
        {"object_ref": None},
        {"vehicle_id": None},
        {"identity": None},
        {"slot_ref": "stand-r1-c1-l1"},
    ):
        data = {**ev.model_dump(mode="json"), **bad}
        with pytest.raises(ValidationError):
            PortEvent.model_validate(data)

    client = _recognition_app(tmp_path)
    res = client.post(
        f"/api/fleet/workcell-observations/{CELL}/port-events",
        headers={"X-Workcell-Observation-Token": "cell-token"},
        json=ev.model_dump(mode="json"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["seq"] == 1

    page = client.get("/api/fleet/port-events", headers=VIEW)
    assert page.status_code == 200, page.text
    assert [e["kind"] for e in page.json()["events"]] == ["container.loaded_for_outbound"]
    assert page.json()["events"][0]["vehicle_id"] == "rosy_46"
    assert page.json()["events"][0]["object_ref"] == "CNTR-OUT-1"


def test_wave4_cell_site_recognition_auth_validation_and_roundtrip(tmp_path):
    client = _recognition_app(tmp_path)

    # Empty store returns 404 until first snapshot is published.
    missing = client.get("/api/fleet/cell-site-recognition", headers=VIEW)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "CELL_SITE_RECOGNITION_NOT_YET_OBSERVED"

    # Unauthenticated and viewer POST are refused.
    assert client.post("/api/fleet/cell-site-recognition", json=_sample_recognition_snapshot()).status_code == 401
    assert client.post(
        "/api/fleet/cell-site-recognition",
        headers={"X-Workcell-Observation-Token": "wrong"},
        json=_sample_recognition_snapshot(),
    ).status_code == 401
    assert client.post(
        "/api/fleet/cell-site-recognition",
        headers=VIEW,
        json=_sample_recognition_snapshot(),
    ).status_code == 403

    # Invalid canonical site ref or EMPTY site with object_class returns 422.
    bad_ref = _sample_recognition_snapshot(
        sites=[{
            "site_ref": "yard-r99-c1-l1",
            "state": "EMPTY",
            "object_class": None,
            "object_ref_read": None,
            "confidence": 0.9,
        }]
    )
    r_bad_ref = client.post("/api/fleet/cell-site-recognition", headers=OP, json=bad_ref)
    assert r_bad_ref.status_code == 422
    assert r_bad_ref.json()["detail"]["code"] == "UNKNOWN_SITE_REF"

    bad_empty = _sample_recognition_snapshot(
        sites=[{
            "site_ref": "stand-r1-c1-l1",
            "state": "EMPTY",
            "object_class": "orange",
            "object_ref_read": None,
            "confidence": 0.9,
        }]
    )
    r_bad_empty = client.post("/api/fleet/cell-site-recognition", headers=OP, json=bad_empty)
    assert r_bad_empty.status_code == 422
    assert r_bad_empty.json()["detail"]["code"] == "INVALID_EMPTY_SITE"

    # Workcell camera observation token publishes valid snapshot -> viewer GET returns it verbatim.
    snap = _sample_recognition_snapshot()
    published = client.post(
        "/api/fleet/cell-site-recognition",
        headers={"X-Workcell-Observation-Token": "cam-token"},
        json=snap,
    )
    assert published.status_code == 200, published.text
    assert published.json()["site_count"] == 2

    fetched = client.get("/api/fleet/cell-site-recognition", headers=VIEW)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["snapshot_id"] == "snap-wave4-1"
    assert [s["site_ref"] for s in fetched.json()["sites"]] == ["yard-r1-c1-l1", "stand-r1-c1-l1"]


def test_wave4_cell_site_recognition_uses_app_state_web_common(tmp_path):
    custom_dir = tmp_path / "web_common"
    custom_dir.mkdir()
    (custom_dir / "cell-site-map.json").write_text(
        '{"schema":"rosy.cell-site-map.v1","revision":9,"status":"verified","tier_height_mm":32.4,'
        '"zones":[{"id":"yard","label":"야드","role":"보관","grid":{"rows":1,"columns":1,"tiers":1},'
        '"slot_cells":1,"slots":[{"id":"yard:r1-s1","row":1,"slot":1,"columns":[1,1],"arms":["arm_a"],'
        '"tiers":[{"tier":1,"id":"yard:r1-s1-t1","item":"ship-h1r0-l0"}]}]}]}\n',
        encoding="utf-8",
    )
    client = _recognition_app(tmp_path, web_common=custom_dir)

    rejected = client.post(
        "/api/fleet/cell-site-recognition",
        headers=OP,
        json=_sample_recognition_snapshot(),  # includes stand-r1-c1-l1, absent from custom map
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "UNKNOWN_SITE_REF"

    accepted = client.post(
        "/api/fleet/cell-site-recognition",
        headers=OP,
        json=_sample_recognition_snapshot(
            sites=[{
                "site_ref": "yard-r1-c1-l1",
                "state": "OCCUPIED",
                "object_class": "orange",
                "object_ref_read": "CNTR-CUSTOM",
                "confidence": 0.95,
            }]
        ),
    )
    assert accepted.status_code == 200, accepted.text


def test_wave4_cell_plan_batch_admit_and_cancel_roundtrip(monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_ab=cell-owner;cell_s=cell-owner")
    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    principals = {
        hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(p, r)
        for t, p, r in (
            ("viewer", "viewer-1", "viewer"),
            ("harbor-svc", "harbor-service", "service"),
            ("operator", "console-human", "operator"),
        )
    }
    require_viewer, require_operator, _, require_proposer = build_role_guards(
        build_authorize(None, principals, None), principals
    )
    app = FastAPI()
    app.state.operator_guard = [Depends(require_operator)]
    app.state.proposer_guard = [Depends(require_proposer)]
    install_pipeline_routes(app, site_maps=maps, read_guard=[Depends(require_viewer)])
    client = TestClient(app)

    created = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "request_key": "wave4-admit-plan-1",
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1"},
        "steps": [{"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a"}],
    })
    assert created.status_code == 200, created.text
    plan = created.json()["plan"]

    rdy = client.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
    admitted = client.post(
        f"/api/fleet/pipeline/cell-plans/{plan['plan_id']}/admit",
        headers=OP,
        json={
            "expected_dispatch_generation": rdy["dispatch_generation"],
            "expected_stop_generation": rdy["stop_generation"],
            "expected_readiness_digest": rdy["readiness_digest"],
            "expected_request_digest": plan["request_digest"],
        },
    )
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["plan"]["status"] == "QUEUED"


def test_wave4_bridge_real_fleet_dynamic_roster(monkeypatch):
    fleet_payload = {
        "gathered_at": 100.0,
        "robots": [
            {"robot_id": "rosy_42", "online": True, "state": {"pose": {"x": 0.1, "y": 0.2, "yaw": 0.0}, "safety": {"estop": True}}},
            {"robot_id": "rosy_99", "online": True, "kind": "pinky", "state": {"pose": {"x": 0.5, "y": -0.1, "yaw": 1.5}, "safety": {"estop": True}}},
            {"robot_id": "arm_c", "online": False, "kind": "arm", "state": {"safety": {"estop": True}}},
        ],
    }
    world = fleet_state_to_world_state(fleet_payload, site_map_sha256="ab" * 32)
    assert world is not None
    assert world["fleet_robots"]["pinkys"] == [*CANONICAL_FLEET_ROBOTS["pinkys"], "rosy_99"]
    assert world["fleet_robots"]["arms"] == [*CANONICAL_FLEET_ROBOTS["arms"], "arm_c"]
    assert world["fleet_summary"] == {"online": 2, "total": 8}
    assert world["safety"]["estop"] is True
    assert world["safety"]["estop_all"] is False

    monkeypatch.setenv("ROSY_WORLD_PINKY_IDS", "rosy_42")
    monkeypatch.setenv("ROSY_WORLD_ARM_IDS", "arm_s")
    only_payload = {
        "gathered_at": 101.0,
        "robots": [
            {"robot_id": "rosy_42", "online": True, "state": {"pose": {"x": 0.1, "y": 0.2, "yaw": 0.0}, "safety": {"estop": True}}},
            {"robot_id": "arm_s", "online": True, "state": {"safety": {"estop": True}}},
        ],
    }
    custom_world = fleet_state_to_world_state(only_payload, site_map_sha256="ab" * 32)
    assert custom_world is not None
    assert custom_world["fleet_robots"] == {"pinkys": ["rosy_42"], "arms": ["arm_s"]}
    assert custom_world["fleet_summary"] == {"online": 2, "total": 2}
    assert custom_world["safety"]["estop_all"] is True
