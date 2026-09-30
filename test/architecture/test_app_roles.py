"""D-370 1·4항: each app keeps one role, and each operation has one owning surface.

The role table lives in the ADR; these checks pin the parts code can break.
Rosy Pilot (`src/hmi/pilot`) is not on main yet. Its check (no `/api/fleet` in Pilot
code) is added in the commit that lands Pilot; until then Pilot is simply not a target,
and `test_pilot_is_not_on_main_yet` turns red the moment the folder appears.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CAMERA_APP = ROOT / "src/site/overhead/android/app/src/main/java"
VISION = ROOT / "src/site/overhead/overhead"
REGISTRY = ROOT / "src/hmi/web_common/surfaces.yaml"

# 1. Ceiling camera app: no CORE API, no Fleet user API (D-341 pairing/v1 excepted),
#    no robot motion or stop (the user decided on 2026-09-30: no stop credential).
CAMERA_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "Fleet user API": re.compile(r"/api/fleet/(?!pairing/v1)"),
    "cmd_vel": re.compile(r"cmd_vel"),
    "estop": re.compile(r"estop", re.IGNORECASE),
}
# 2. Site Vision: no CORE API, no robot command, and to Fleet only the sighting write.
VISION_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "cmd_vel": re.compile(r"cmd_vel"),
    "Fleet route other than sightings": re.compile(r"/api/fleet/(?!sightings\b)"),
}
# 3. Fleet vision routes pass the video-route regex of test_no_video_relay because they
#    only issue a lease; the browser fetches frames from Vision directly (D-318).
FLEET_VISION_ROUTES = {"/api/fleet/vision/sources", "/api/fleet/vision/lease"}
LEASE_KEYS = {"source_id", "lease", "frame_path", "expires_in_s"}
# 5. Only e-stop may be owned by several surfaces (D-370 4항).
SHARED_OWNERSHIP = {"estop"}


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
    """Operations owned by two surfaces, except e-stop and entries marked transitional."""
    owners: dict[str, list[str]] = {}
    for row in rows:
        for entry in row.get("owns") or []:
            if isinstance(entry, dict):
                if entry.get("transitional"):
                    continue
                entry = entry.get("id")
            owners.setdefault(entry, []).append(row["id"])
    return [f"{name}: {', '.join(ids)}" for name, ids in sorted(owners.items())
            if len(ids) > 1 and name not in SHARED_OWNERSHIP]


def test_camera_app_has_no_robot_or_fleet_user_calls():
    assert CAMERA_APP.is_dir()
    assert _hits(CAMERA_APP, (".kt", ".java"), CAMERA_FORBIDDEN) == []


def test_vision_has_no_robot_command_and_writes_only_sightings_to_fleet():
    assert VISION.is_dir()
    assert _hits(VISION, (".py",), VISION_FORBIDDEN) == []
    assert "/api/fleet/sightings" in (VISION / "publish.py").read_text(encoding="utf-8")


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


def test_pilot_is_not_on_main_yet():
    """When Pilot lands, add its role check here (no /api/fleet in src/hmi/pilot)."""
    assert not (ROOT / "src/hmi/pilot").exists()


def test_each_operation_has_one_owner():
    rows = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["surfaces"]
    assert owns_overlaps(rows) == []
    owners = {entry if isinstance(entry, str) else entry["id"]
              for row in rows for entry in row.get("owns") or []}
    assert {"estop", "manual-drive", "site-monitoring", "robot-detail"} <= owners
    camera = next(row for row in rows if row["id"] == "overhead-camera-app")
    assert "estop" not in camera["owns"]


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
