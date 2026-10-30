"""Cell object catalogue: the arm's catalogue file read only, an unmeasured object shown blocked (D-934, D-935)."""
import json

from fleet.server.cell_object_catalog import ENV
from test_cell_job_api import _setup

VIEWER = {"Authorization": "Bearer viewer-secret"}


def catalogue(tmp_path, body):
    path = tmp_path / "object-catalog.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_viewer_sees_masses_and_an_unmeasured_object_is_blocked(tmp_path, monkeypatch):
    path = catalogue(tmp_path, {"schema": "rosy.omx-object-catalog.v1", "objects": [
        {"id": "container-2", "kind": "green shipping container", "length_mm": 60, "width_mm": 30,
         "top_height_mm": 30, "tolerance_mm": 9, "grasp": {}, "mass_kg": 0.04823,
         "mass_measured": {"at": "2026-10-30T12:00:00+00:00", "source": "cell_scale", "reading": "48.23 g"}},
        {"id": "container-3", "length_mm": 90, "width_mm": 30, "top_height_mm": 30, "mass_kg": None}]})
    before = path.read_bytes()
    monkeypatch.setenv(ENV, str(path))
    client, _, _ = _setup(tmp_path)
    response = client.get("/api/fleet/cell-app/object-catalog", headers=VIEWER)
    assert response.status_code == 200
    first, second = response.json()["objects"]
    assert first["mass_kg"] == 0.04823 and first["mass_measured"]["reading"] == "48.23 g"
    assert first["carry"].startswith("ok") and "tolerance_mm" not in first
    assert second["mass_kg"] is None and second["mass_measured"] is None
    assert second["carry"] == "blocked: no measured mass (D-935)"
    assert path.read_bytes() == before  # read only
    assert client.get("/api/fleet/cell-app/object-catalog").status_code == 401


def test_an_unconfigured_or_wrong_catalogue_is_refused(tmp_path, monkeypatch):
    client, _, _ = _setup(tmp_path)
    monkeypatch.delenv(ENV, raising=False)
    missing = client.get("/api/fleet/cell-app/object-catalog", headers=VIEWER)
    assert missing.status_code == 503 and missing.json()["detail"]["code"] == "CELL_OBJECT_CATALOG_UNAVAILABLE"
    monkeypatch.setenv(ENV, str(catalogue(tmp_path, {"schema": "rosy.other.v1", "objects": []})))
    wrong = client.get("/api/fleet/cell-app/object-catalog", headers=VIEWER)
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "CELL_OBJECT_CATALOG_INVALID"
