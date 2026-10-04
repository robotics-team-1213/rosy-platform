"""D-370 1·4항: each app keeps one role, and each operation has one owning surface.

The role table lives in the ADR; these checks pin the parts code can break.
Rosy Pilot is a live one-robot surface. D-425 adds explicit API-owner declarations
and real server refusal/write checks in test/test_app_ownership_contracts.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CAMERA_APP = ROOT / "operations/ui/cam/app/src/main/java"
VISION = ROOT / "operations/vision/rosy_vision"
REGISTRY = ROOT / "shared/web/surfaces.yaml"

# 1. Rosy Cam: no CORE API or Fleet user API; D-341 v1 / D-456 v2 camera pairing only.
#    no robot motion or stop (the user decided on 2026-09-30: no stop credential).
CAMERA_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "Fleet user API": re.compile(r'''/api/fleet/(?!pairing/v(?:1|2)(?:[/"'$]|$))'''),
    "cmd_vel": re.compile(r"cmd_vel"),
    "estop": re.compile(r"estop", re.IGNORECASE),
}
# 2. Rosy Vision: no CORE API, no robot command, and to Fleet only the sighting write, the
#    D-457 detections write and own-config read, plus the D-341 12 read of paired-camera
#    credential digests.
VISION_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "cmd_vel": re.compile(r"cmd_vel"),
    "Fleet route other than sightings or detections": re.compile(
        r"/api/fleet/(?!sightings\b)(?!detections\b)(?!pairing/v1/credentials\b)"),
}
# 3. Fleet vision routes pass the video-route regex of test_no_video_relay because they
#    only issue a lease; the browser fetches frames from Vision directly (D-318).
FLEET_VISION_ROUTES = {"/api/fleet/vision/sources", "/api/fleet/vision/lease"}
LEASE_KEYS = {"source_id", "lease", "frame_path", "expires_in_s"}
# 5. Only e-stop may be owned by several surfaces (D-370 4항).
SHARED_OWNERSHIP = {"estop"}
# A transitional overlap must name the ADR that retires it.
TRANSITIONAL = re.compile(r"\bD-\d+")


def _hits(root: Path, suffixes: tuple[str, ...], rules: dict[str, re.Pattern]) -> list[str]:
    found = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in suffixes or "test" in path.relative_to(root).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, pattern in rules.items():
                if pattern.search(line):
                    found.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {label}")
    return found


def owns_overlaps(rows: list[dict]) -> list[str]:
    """Operations owned by two surfaces, except e-stop and entries marked transitional.

    An entry counts as transitional only when its note cites an ADR (``D-<n>``).
    """
    owners: dict[str, list[str]] = {}
    for row in rows:
        for entry in row.get("owns") or []:
            if isinstance(entry, dict):
                if TRANSITIONAL.search(str(entry.get("transitional") or "")):
                    continue
                entry = entry.get("id")
            owners.setdefault(entry, []).append(row["id"])
    return [f"{name}: {', '.join(ids)}" for name, ids in sorted(owners.items())
            if len(ids) > 1 and name not in SHARED_OWNERSHIP]


def test_camera_app_has_no_robot_or_fleet_user_calls():
    assert CAMERA_APP.is_dir()
    assert _hits(CAMERA_APP, (".kt", ".java"), CAMERA_FORBIDDEN) == []


def test_camera_pairing_namespace_exemption_keeps_user_routes_forbidden():
    forbidden = CAMERA_FORBIDDEN["Fleet user API"]
    for path in ("/api/fleet/pairing/v1/requests", "/api/fleet/pairing/v2/requests",
                 '/api/fleet/pairing/v2$path"'):
        assert forbidden.search(path) is None
    for path in ("/api/fleet/robots/robot/route", "/api/fleet/users",
                 "/api/fleet/tasks", "/api/fleet/pairing/v20/requests",
                 "/api/fleet/pairing/v2admin", "/api/fleet/pairing/v3/requests"):
        assert forbidden.search(path), path
    assert CAMERA_FORBIDDEN["CORE API"].search("/api/v1/control/teleop")


def test_vision_has_no_robot_command_and_writes_only_sightings_and_detections_to_fleet():
    assert VISION.is_dir()
    assert _hits(VISION, (".py",), VISION_FORBIDDEN) == []
    assert "/api/fleet/sightings" in (VISION / "publish.py").read_text(encoding="utf-8")
    assert "/api/fleet/detections" in (VISION / "track" / "fleet_client.py").read_text(encoding="utf-8")


def test_fleet_vision_routes_only_issue_leases_without_bytes():
    from fastapi.testclient import TestClient

    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole

    app = create_app(FleetConsole([], []), vision_lease_secret="v" * 32,
                     vision_sources=("ceiling-north",))
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert {path for path in paths if "vision" in path} == FLEET_VISION_ROUTES
    client = TestClient(app)
    sources = client.get("/api/fleet/vision/sources")
    lease = client.post("/api/fleet/vision/lease", json={"source_id": "ceiling-north"})
    for response in (sources, lease):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert len(response.content) < 1024
    assert sources.json() == {"sources": ["ceiling-north"]}
    body = lease.json()
    assert set(body) == LEASE_KEYS
    assert all(isinstance(value, (str, int)) for value in body.values())
    assert not body["frame_path"].startswith("/api/fleet/")


def test_pilot_stays_a_one_robot_surface():
    """D-370 1항: Pilot never calls Fleet — it drives one robot through that robot's CORE."""
    pilot = ROOT / "middleware/ui/pilot"
    assert pilot.is_dir()
    calls = [path.relative_to(ROOT).as_posix() for path in pilot.rglob("*")
             if path.suffix in {".js", ".html"} and "test" not in path.parts
             and "/api/fleet" in path.read_text(encoding="utf-8")]
    assert calls == []


def test_shared_transport_and_controls_do_not_choose_operational_endpoints():
    """D-425: service adapters can name their contract; transport/UI cannot choose one."""
    shared = ROOT / "shared/web"
    adapters = {"core-client.js", "fleet-client.js"}
    # Evidence labels can name a route without issuing a request to it.
    dispatch = re.compile(r"\b(?:fetch|api|postJson|request)\s*\(\s*['\"`]/api/(?:v1|fleet)/")
    hits = []
    for path in sorted(shared.glob("*.js")):
        if path.name not in adapters:
            hits.extend([
                f"{path.relative_to(ROOT).as_posix()}:{number}: operational endpoint"
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if dispatch.search(line)
            ])
    assert hits == []


def test_each_operation_has_one_owner():
    rows = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["surfaces"]
    assert owns_overlaps(rows) == []
    owners = {entry if isinstance(entry, str) else entry["id"]
              for row in rows for entry in row.get("owns") or []}
    assert {"estop", "manual-drive", "site-monitoring", "robot-detail"} <= owners
    camera = next(row for row in rows if row["id"] == "cam")
    camera_owns = {entry if isinstance(entry, str) else entry["id"] for entry in camera["owns"]}
    assert "estop" not in camera_owns
    notes = [entry["transitional"] for row in rows for entry in row.get("owns") or []
             if isinstance(entry, dict) and "transitional" in entry]
    assert notes and all(TRANSITIONAL.search(str(note)) for note in notes), notes


def test_overlap_check_allows_only_estop_and_transitional():
    rows = [
        {"id": "dashboard", "owns": ["estop", {"id": "manual-drive", "transitional": "D-370 4항 1"}]},
        {"id": "pilot", "owns": ["estop", "manual-drive"]},
        {"id": "fleet", "owns": ["estop", "mission"]},
    ]
    assert owns_overlaps(rows) == []
    rows[0]["owns"][1] = "manual-drive"
    rows[2]["owns"].append("manual-drive")
    assert owns_overlaps(rows) == ["manual-drive: dashboard, pilot, fleet"]


def test_transitional_without_an_adr_number_is_an_overlap():
    rows = [
        {"id": "dashboard", "owns": [{"id": "manual-drive", "transitional": "later"}]},
        {"id": "pilot", "owns": ["manual-drive"]},
    ]
    assert owns_overlaps(rows) == ["manual-drive: dashboard, pilot"]
    rows[0]["owns"][0]["transitional"] = "D-370 4항 1"
    assert owns_overlaps(rows) == []
