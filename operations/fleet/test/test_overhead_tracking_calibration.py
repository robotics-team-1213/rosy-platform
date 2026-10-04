"""D-457 1: an approved paint fit becomes one validated, revisioned record per camera source."""

import json
from pathlib import Path

import pytest

from fleet.server.sighting_store import SightingStore
from fleet.server.tracking_calibration import REVISION_PREFIX, TrackingCalibrationStore, build_record

FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
EXAMPLE = FIXTURE["config_example"]["calibration"]


def _record(**changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet",
                map_to_image=EXAMPLE["map_to_image"], image_width=640, image_height=360,
                track_bounds_m=(0.0, 0.0, 6.4, 3.6), lens=None, fit_score=0.81, frame_seq=12,
                approved_by="site-console", approved_at=1_790_000_000.0)
    args.update(changes)
    return build_record(**args)


def test_record_has_the_shape_vision_reads():
    row = _record().to_dict()
    assert set(row) == set(EXAMPLE)
    for key in set(EXAMPLE) - {"calibration_revision"}:
        assert row[key] == EXAMPLE[key], key
    revision = row["calibration_revision"]
    assert revision.startswith(REVISION_PREFIX) and len(revision) == len(REVISION_PREFIX) + 12


def test_revision_is_deterministic_and_follows_the_fit():
    assert _record().calibration_revision == _record().calibration_revision
    moved = _record(map_to_image=[101.0] + EXAMPLE["map_to_image"][1:])
    assert moved.calibration_revision != _record().calibration_revision
    lens = _record(lens={"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9})
    assert lens.to_dict()["lens"] == {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9}
    assert lens.calibration_revision != _record().calibration_revision


@pytest.mark.parametrize("changes", [
    {"map_to_image": [1.0] * 8},
    {"map_to_image": [float("nan")] + [1.0] * 8},
    {"map_to_image": [0.0] * 9},
    {"image_width": 0},
    {"image_height": 9000},
    {"track_bounds_m": (1.0, 0.0, 1.0, 3.6)},
    {"fit_score": 1.5},
    {"lens": {"kind": "standard", "focal_mm": -1.0, "hfov_deg": 60.0}},
    {"lens": {"kind": "standard"}},
    {"frame_seq": -1},
    {"approved_by": ""},
])
def test_invalid_records_are_refused(changes):
    with pytest.raises(ValueError):
        _record(**changes)


def test_sqlite_store_persists_and_audits(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = TrackingCalibrationStore(path)
    record = _record()
    store.put(record)
    again = TrackingCalibrationStore(path)
    assert again.get("ceiling_north") == record
    assert again.delete("ceiling_north", principal_id="operator-1", at=1_790_000_100.0) is True
    assert again.delete("ceiling_north", principal_id="operator-1", at=1_790_000_101.0) is False
    assert TrackingCalibrationStore(path).get("ceiling_north") is None
    assert [(row["event"], row["principal_id"]) for row in again.audit_events()] == [
        ("calibration.approved", "site-console"), ("calibration.revoked", "operator-1")]


def test_store_shares_the_sightings_database_without_touching_it(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    SightingStore(path)
    TrackingCalibrationStore(path).put(_record())
    assert SightingStore(path).load_latest() == {}
    assert TrackingCalibrationStore(path).get("ceiling_north") == _record()


def test_memory_store_needs_no_file():
    store = TrackingCalibrationStore()
    store.put(_record())
    assert store.all() == [_record()]
    assert store.audit_events() == []
    assert store.delete("ceiling_north", principal_id="operator-1", at=0.0) is True
    assert store.get("ceiling_north") is None


@pytest.mark.parametrize("changes", [
    {"map_to_image": [float("inf")] + [1.0] * 8},
    {"map_to_image": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 0.0, 0.0, 1.0]},
    {"map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 1.0, 0.0, -3.0]},
    {"image_width": True},
    {"image_width": 640.0},
    {"approved_at": float("nan")},
    {"approved_at": float("inf")},
    {"approved_at": 0.0},
    {"source_id": ""},
    {"map_id": ""},
])
def test_more_invalid_records_are_refused(changes):
    with pytest.raises(ValueError):
        _record(**changes)


def test_delete_refuses_non_finite_time(tmp_path):
    store = TrackingCalibrationStore(tmp_path / "fleet.sqlite3")
    store.put(_record())
    with pytest.raises(ValueError):
        store.delete("ceiling_north", principal_id="operator-1", at=float("nan"))
    assert store.get("ceiling_north") is not None
    assert [row["event"] for row in store.audit_events()] == ["calibration.approved"]


def test_put_twice_replaces_and_audits_both(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = TrackingCalibrationStore(path)
    store.put(_record())
    newer = _record(approved_at=1_790_000_050.0)
    store.put(newer)
    assert TrackingCalibrationStore(path).get("ceiling_north") == newer
    assert len(store.audit_events()) == 2


def test_all_is_sorted_by_source():
    store = TrackingCalibrationStore()
    store.put(_record(source_id="b"))
    store.put(_record(source_id="a"))
    assert [record.source_id for record in store.all()] == ["a", "b"]


def test_corrupt_rows_are_skipped_not_fatal(tmp_path, caplog):
    import sqlite3
    path = tmp_path / "fleet.sqlite3"
    TrackingCalibrationStore(path).put(_record())
    good = _record().to_dict()
    tampered = dict(good, source_id="tampered", calibration_revision="paint-000000000000")
    singular = dict(good, source_id="singular", map_to_image=[1.0] * 9)
    with sqlite3.connect(path) as connection:
        for name, payload in (("tampered", json.dumps(tampered)), ("singular", json.dumps(singular)),
                              ("garbage", "{not json")):
            connection.execute("INSERT INTO tracking_calibrations(source_id, payload_json) VALUES (?, ?)",
                               (name, payload))
    store = TrackingCalibrationStore(path)
    assert [record.source_id for record in store.all()] == ["ceiling_north"]
    assert "tampered" in caplog.text
