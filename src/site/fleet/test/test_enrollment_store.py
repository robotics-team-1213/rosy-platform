"""D-352 S1: the Fleet-owned robot enrollment register and its sealed credentials."""

from __future__ import annotations

import base64
import os
import sqlite3
from contextlib import closing

import pytest

from fleet.server.enrollment_store import (
    CredentialKeyError,
    EnrollmentStore,
    SealError,
    load_key_file,
    rekey,
    seal,
    unseal,
)

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))
SECRET = "tok-" + "Zq7RkXw2Lm9"  # assembled: no literal secret in tracked files


def _key_file(tmp_path, content: bytes, name: str = "robot.key"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _row(robot_id: str = "rosy_09", **overrides) -> dict:
    row = {
        "robot_id": robot_id, "hostname": "rosy-pinky-8kcn", "serial_number": "sn-1",
        "device_uid": None, "discovery_name": "rosy-pinky-8kcn", "address": "192.168.1.202:8080",
        "token_id": "tid-1", "role": "operator", "source": "pair-physical",
        "expires_at": "2026-10-06T00:00:00+00:00", "fleet_expires_at": 2000.0,
        "warn_at": 1800.0, "principal_id": "alice", "state": "active",
    }
    row.update(overrides)
    return row


def test_seal_round_trips_and_every_bound_field_is_checked():
    blob = seal(KEY, SECRET, slot="rest", robot_id="rosy_09", token_id="tid-1")
    assert unseal(KEY, blob, slot="rest", robot_id="rosy_09", token_id="tid-1") == SECRET
    for changed in ({"slot": "agent"}, {"robot_id": "rosy_10"}, {"token_id": "tid-2"}):
        bound = {"slot": "rest", "robot_id": "rosy_09", "token_id": "tid-1", **changed}
        with pytest.raises(SealError):
            unseal(KEY, blob, **bound)
    with pytest.raises(SealError):
        unseal(OTHER_KEY, blob, slot="rest", robot_id="rosy_09", token_id="tid-1")


def test_each_seal_uses_a_fresh_nonce():
    first = seal(KEY, SECRET, slot="rest", robot_id="r", token_id="t")
    second = seal(KEY, SECRET, slot="rest", robot_id="r", token_id="t")
    assert first[:12] != second[:12] and first != second


def test_length_prefixed_aad_separates_concatenation_ambiguity():
    """("ab", "c") and ("a", "bc") would collide if the fields were only joined."""
    blob = seal(KEY, SECRET, slot="rest", robot_id="ab", token_id="c")
    with pytest.raises(SealError):
        unseal(KEY, blob, slot="rest", robot_id="a", token_id="bc")


def test_unknown_slot_is_refused():
    with pytest.raises(ValueError):
        seal(KEY, SECRET, slot="other", robot_id="r", token_id="t")


def test_key_file_is_one_base64_line_of_32_bytes(tmp_path):
    line = base64.b64encode(KEY)
    assert len(line) == 44
    assert load_key_file(_key_file(tmp_path, line + b"\n")) == KEY
    assert load_key_file(_key_file(tmp_path, line)) == KEY


@pytest.mark.parametrize("content", [
    KEY,                                            # raw 32 bytes
    base64.b64encode(KEY[:16]) + b"\n",             # short
    base64.b64encode(KEY + b"\x00") + b"\n",        # long
    b" " + base64.b64encode(KEY) + b"\n",           # whitespace mixed in
    base64.b64encode(KEY)[:20] + b" " + base64.b64encode(KEY)[20:],
    base64.b64encode(KEY) + b"\n\n",                # two lines
    b"",
])
def test_malformed_key_files_are_refused(tmp_path, content):
    with pytest.raises(CredentialKeyError):
        load_key_file(_key_file(tmp_path, content))


def test_missing_key_file_is_a_key_error(tmp_path):
    with pytest.raises(CredentialKeyError):
        load_key_file(tmp_path / "absent.key")


def test_register_round_trip_keeps_no_plaintext_in_the_database_file(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = EnrollmentStore(path)
    store.insert(_row(), seal(KEY, SECRET, slot="rest", robot_id="rosy_09", token_id="tid-1"))

    rows = store.rows()
    assert [row["robot_id"] for row in rows] == ["rosy_09"]
    assert "ciphertext" not in rows[0] and SECRET not in repr(rows)
    assert unseal(KEY, store.ciphertext("rosy_09"), slot="rest", robot_id="rosy_09",
                  token_id="tid-1") == SECRET
    for candidate in path.parent.glob("fleet.sqlite3*"):
        assert SECRET.encode() not in candidate.read_bytes()


def test_register_states_are_limited_to_the_first_slice(tmp_path):
    store = EnrollmentStore(tmp_path / "fleet.sqlite3")
    store.insert(_row(), b"x" * 40)
    for state in ("needs_new_code", "address_changed", "pending_logout", "active"):
        store.update("rosy_09", state=state)
        assert store.get("rosy_09")["state"] == state
    with pytest.raises(ValueError):
        store.update("rosy_09", state="conflict")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert(_row(), b"x" * 40)
    store.delete("rosy_09")
    assert store.get("rosy_09") is None


def test_rekey_reseals_every_row_in_one_transaction(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = EnrollmentStore(path)
    for rid in ("rosy_09", "rosy_10"):
        store.insert(_row(rid, token_id=f"tid-{rid}"),
                     seal(KEY, SECRET + rid, slot="rest", robot_id=rid, token_id=f"tid-{rid}"))

    assert rekey(path, KEY, OTHER_KEY) == 2
    for rid in ("rosy_09", "rosy_10"):
        blob = store.ciphertext(rid)
        assert unseal(OTHER_KEY, blob, slot="rest", robot_id=rid, token_id=f"tid-{rid}") == SECRET + rid
        with pytest.raises(SealError):
            unseal(KEY, blob, slot="rest", robot_id=rid, token_id=f"tid-{rid}")


def test_rekey_with_the_wrong_old_key_changes_nothing(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = EnrollmentStore(path)
    blob = seal(KEY, SECRET, slot="rest", robot_id="rosy_09", token_id="tid-1")
    store.insert(_row(), blob)
    with pytest.raises(SealError):
        rekey(path, OTHER_KEY, KEY)
    assert store.ciphertext("rosy_09") == blob


def test_audit_is_bounded_and_records_device_kind(tmp_path):
    store = EnrollmentStore(tmp_path / "fleet.sqlite3", audit_limit=5)
    for index in range(8):
        store.audit(action="enroll", outcome="enrolled", principal_id="alice",
                    target=f"rosy_{index:02d}")
    rows = store.audit_rows()
    assert len(rows) == 5
    assert rows[-1]["target"] == "rosy_07" and rows[0]["target"] == "rosy_03"
    assert {row["device_kind"] for row in rows} == {"robot"}


def test_existing_d341_audit_table_gets_the_device_kind_column(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """CREATE TABLE device_pairing_audit (
                   audit_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                   action TEXT NOT NULL, outcome TEXT NOT NULL,
                   principal_id TEXT, target TEXT)""")
        connection.execute("INSERT INTO device_pairing_audit(at, action, outcome, principal_id, target)"
                           " VALUES (1.0, 'approve', 'approved', 'bob', 'cam-1')")
        connection.commit()

    store = EnrollmentStore(path)
    store.audit(action="enroll", outcome="enrolled", principal_id="alice", target="rosy_09")
    kinds = [(row["target"], row["device_kind"]) for row in store.audit_rows()]
    assert kinds == [("cam-1", "overhead-camera"), ("rosy_09", "robot")]


def test_retired_ids_are_pending_logout_rows_and_audited_unenrollments(tmp_path):
    store = EnrollmentStore(tmp_path / "fleet.sqlite3")
    store.insert(_row("rosy_09", state="pending_logout"), b"x" * 40)
    store.insert(_row("rosy_10"), b"x" * 40)
    store.audit(action="unenroll", outcome="removed", principal_id="alice", target="rosy_11")
    assert store.retired_robot_ids() == {"rosy_09", "rosy_11"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_database_file_is_private(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    EnrollmentStore(path)
    assert path.stat().st_mode & 0o077 == 0
