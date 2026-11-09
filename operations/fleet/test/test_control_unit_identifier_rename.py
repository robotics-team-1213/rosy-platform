"""D-1011: the arm cell unit keeps accepting its pre-rename id CELL-A everywhere input arrives."""

import json
import sqlite3

from core_common.protocol.integrated_control import ControlDispatchFence, ControlStopIngress
from fleet.server.control_stop_schema import ensure_schema
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_runtime import load_control_unit
from fleet.server.control_unit_stops import canonical_stop_ingress
from fleet.server.control_unit_store import ControlUnitStore


MANIFEST = {"revision": "v1", "units": [
    {"id": "R", "resources": ["robot:p1"]},
    {"id": "ARM-CELL", "parent": "R", "resources": ["workcell:arm_a"]}]}


def test_topology_and_scope_resolution_accept_the_pre_rename_id():
    topology = ControlUnitTopology.from_mapping(MANIFEST)
    assert topology.unit("CELL-A").unit_id == "ARM-CELL"
    assert topology.next_hop("R", "CELL-A") == "ARM-CELL"
    assert topology.child("R", "CELL-A").unit_id == "ARM-CELL"
    try:
        topology.unit("CELL-Z")
    except ValueError as exc:
        assert str(exc) == "UNKNOWN_CONTROL_UNIT"
    else:
        raise AssertionError("an unrelated unit id must stay unknown")


def test_peer_configuration_accepts_a_pre_rename_neighbor_key(tmp_path):
    directory = tmp_path / "unit"
    directory.mkdir()
    (directory / "token").write_text("neighbor-secret", encoding="ascii")
    (directory / "control-unit.yaml").write_text(
        "unit_id: R\n"
        "manifest:\n"
        f"  revision: {MANIFEST['revision']}\n"
        "  units:\n"
        "    - id: R\n"
        "      resources: [robot:p1]\n"
        "    - id: ARM-CELL\n"
        "      parent: R\n"
        "      resources: [workcell:arm_a]\n"
        "peers:\n"
        "  CELL-A:\n"
        "    url: https://peer-arm-cell:8543\n"
        "    token_file: token\n",
        encoding="utf-8")
    config = load_control_unit(directory / "control-unit.yaml")
    assert set(config.peers) == {"ARM-CELL"}
    (directory / "token2").write_text("neighbor-secret-2", encoding="ascii")
    duplicate = ("unit_id: R\nmanifest:\n  revision: v1\n  units:\n"
                 "    - id: R\n      resources: [robot:p1]\n"
                 "    - id: ARM-CELL\n      parent: R\n      resources: [workcell:arm_a]\n"
                 "peers:\n"
                 "  CELL-A:\n    url: https://peer-arm-cell:8543\n    token_file: token\n"
                 "  ARM-CELL:\n    url: https://peer-arm-cell:8543\n    token_file: token2\n")
    (directory / "duplicate.yaml").write_text(duplicate, encoding="utf-8")
    try:
        load_control_unit(directory / "duplicate.yaml")
    except ValueError as exc:
        assert str(exc) == "CONTROL_UNIT_NEIGHBOR_CONFIGURATION_MISMATCH"
    else:
        raise AssertionError("both the alias and the renamed key must not be accepted together")


def _legacy_journal(path):
    store = ControlUnitStore(path, unit_id="CELL-A")
    store.create("R", "arm-1", {"target_unit": "CELL-A", "note": "was written as CELL-A here",
                                "other_unit": "CELL-B", "robot_id": "p1", "goal": {}},
                 owner_unit="CELL-A", config_revision="v1")
    with sqlite3.connect(path) as connection:
        ensure_schema(connection)
        connection.execute(
            "INSERT INTO fleet_control_stops VALUES ('R','s-1','CELL-A','v1','CELL-A',?,'operator',1,?)",
            (json.dumps({"target_unit": "CELL-A"}), "2026-11-10T00:00:00+00:00"))
        connection.execute(
            "INSERT INTO fleet_control_stop_deliveries VALUES "
            "('R','s-1','CELL-A','LOCAL',?,'REQUESTED',NULL,?,0,NULL,NULL,NULL)",
            (json.dumps({"units": ["CELL-A"]}), json.dumps([{"unit_id": "CELL-A", "state": "REQUESTED"}])))
    return store


def test_store_migration_rewrites_the_pre_rename_journal_once(tmp_path):
    path = tmp_path / "unit.sqlite3"
    _legacy_journal(path)
    migrated = ControlUnitStore(path, unit_id="ARM-CELL")  # runs the D-1011 migration
    assert migrated.unit_id == "ARM-CELL"
    row = migrated.get("R", "arm-1")
    assert row["owner_unit"] == "ARM-CELL"
    assert row["request"]["target_unit"] == "ARM-CELL"
    # exact values only: prose mentioning the old id and other units are untouched
    assert row["request"]["note"] == "was written as CELL-A here"
    assert row["request"]["other_unit"] == "CELL-B"
    with sqlite3.connect(path) as connection:
        identity = connection.execute("SELECT unit_id FROM fleet_control_unit_identity").fetchone()[0]
        stops = dict(connection.execute(
            "SELECT unit_id, target_unit, body_json FROM fleet_control_stops").fetchone())
        delivery = connection.execute(
            "SELECT delivery_unit, assigned_json, results_json FROM fleet_control_stop_deliveries"
        ).fetchone()
        audit = connection.execute(
            "SELECT from_id, to_id, COUNT(*) FROM fleet_control_unit_identifier_events "
            "GROUP BY from_id, to_id").fetchall()
    assert identity == "ARM-CELL"
    assert stops["unit_id"] == "ARM-CELL" and stops["target_unit"] == "ARM-CELL"
    assert json.loads(stops["body_json"]) == {"target_unit": "ARM-CELL"}
    assert delivery[0] == "ARM-CELL"
    assert json.loads(delivery[1]) == {"units": ["ARM-CELL"]}
    assert json.loads(delivery[2]) == [{"unit_id": "ARM-CELL", "state": "REQUESTED"}]
    assert audit == [("CELL-A", "ARM-CELL", 1)]
    ControlUnitStore(path, unit_id="ARM-CELL")  # idempotent: no second rewrite or audit row
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM fleet_control_unit_identifier_events").fetchone()[0] == 1


def test_store_without_the_renamed_unit_leaves_the_journal_alone(tmp_path):
    path = tmp_path / "unit.sqlite3"
    _legacy_journal(path)
    reopened = ControlUnitStore(path, unit_id="CELL-A")  # still the old config: nothing migrates
    assert reopened.get("R", "arm-1")["owner_unit"] == "CELL-A"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='fleet_control_unit_identifier_events'"
        ).fetchone()[0] == 0


def test_stop_ingress_canonicalizes_the_pre_rename_target_and_fences():
    body = ControlStopIngress(
        origin_id="R", stop_id="s-1", config_revision="v1", target_unit="CELL-A",
        expected_controls={"CELL-A": ControlDispatchFence(authority_epoch=0, generation=1),
                           "R": ControlDispatchFence(authority_epoch=0, generation=2)})
    canonical = canonical_stop_ingress(body)
    assert canonical.target_unit == "ARM-CELL"
    assert set(canonical.expected_controls) == {"ARM-CELL", "R"}
    assert canonical.expected_controls["ARM-CELL"].generation == 1
