import sqlite3

from fleet.server.sighting_store import SightingStore


def test_store_persists_only_derived_sightings_and_audits_acceptance(tmp_path):
    database = tmp_path / "fleet" / "sightings.sqlite3"
    store = SightingStore(database)
    row = {
        "robot_id": "rosy_01", "source_id": "ceiling_north", "x": 1.2, "y": 0.4,
        "yaw": -0.1, "captured_at": 100.0, "received_at": 100.1, "seq": 8,
        "map_id": "site-v1", "calibration_revision": "cal-v3",
        "processor_revision": "aruco-v1", "quality": None,
        "corner_marker_ids": [30, 31, 32, 33],
    }

    store.save_sighting(row)

    restored = SightingStore(database)
    assert restored.load_latest() == {"rosy_01": row}
    assert restored.audit_events() == [{
        "event": "sighting.accepted", "robot_id": "rosy_01",
        "source_id": "ceiling_north", "seq": 8, "captured_at": 100.0,
        "received_at": 100.1,
    }]
    assert b"source-secret" not in database.read_bytes()


def test_store_backup_restores_latest_rows_and_audit_events(tmp_path):
    database = tmp_path / "site.sqlite3"
    backup = tmp_path / "backup" / "site.sqlite3"
    store = SightingStore(database)
    store.save_sighting({
        "robot_id": "rosy_01", "source_id": "ceiling_north", "x": 0.0, "y": 0.0,
        "yaw": 0.0, "captured_at": 100.0, "received_at": 100.0, "seq": 1,
        "map_id": "site-v1", "calibration_revision": "cal-v3",
        "processor_revision": "aruco-v1", "quality": None,
        "corner_marker_ids": [30, 31, 32, 33],
    })

    store.backup(backup)

    restored = SightingStore(backup)
    assert restored.load_latest()["rosy_01"]["seq"] == 1
    assert len(restored.audit_events()) == 1
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
