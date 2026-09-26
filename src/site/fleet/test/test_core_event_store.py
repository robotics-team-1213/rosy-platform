from fleet.server.core_event_store import CoreEventStore


def test_store_is_idempotent_and_uses_monotonic_audit_cursors(tmp_path):
    store = CoreEventStore(tmp_path / "fleet.sqlite3")
    event = {
        "event_id": "evt-1", "seq": 1, "ts": "2026-09-26T00:00:00Z",
        "robot_id": "rosy_01", "type": "nav.completed", "severity": "info",
        "source": "navigation", "data": {"goal_id": "goal-1"},
    }

    assert store.append_event(event) is True
    assert store.append_event(event) is False
    assert store.append_event({**event, "event_id": "evt-2", "seq": 2}) is True
    page = store.read_events(limit=1)
    next_page = store.read_events(after_id=page[0]["audit_id"], limit=1)

    assert page[0]["event"]["event_id"] == "evt-1"
    assert next_page[0]["event"]["event_id"] == "evt-2"
    assert next_page[0]["audit_id"] > page[0]["audit_id"]


def test_store_rejects_secret_bearing_or_oversized_event_data(tmp_path):
    store = CoreEventStore(tmp_path / "fleet.sqlite3")
    base = {"event_id": "evt-1", "seq": 1, "robot_id": "rosy_01",
            "type": "nav.completed", "data": {}}

    sensitive_field = "pairing_" + "token"
    for event in (
        {**base, "data": {"nested": {sensitive_field: "hidden"}}},
        {**base, "event_id": "evt-2", "data": {"message": "x" * 70000}},
    ):
        try:
            store.append_event(event)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe events must not be persisted")
    assert store.read_events() == []


def test_reusing_event_id_for_different_payload_is_rejected(tmp_path):
    store = CoreEventStore(tmp_path / "fleet.sqlite3")
    event = {"event_id": "evt-1", "seq": 1, "robot_id": "rosy_01",
             "type": "nav.completed", "data": {"goal_id": "goal-1"}}
    assert store.append_event(event) is True

    try:
        store.append_event({**event, "data": {"goal_id": "goal-2"}})
    except ValueError:
        pass
    else:
        raise AssertionError("event identity reuse must not hide changed event content")
