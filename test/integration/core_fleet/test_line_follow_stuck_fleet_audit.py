"""D-407 lane stuck events against Fleet's event-store credential filter.

Moved out of middleware/core/gateway/test/test_line_follow_stuck_api.py so the pinky-owned
gateway suite imports no Fleet code; the CORE fixture and helpers come from that suite.
"""

from __future__ import annotations

from fleet.server import core_event_store
from test_line_follow_stuck_api import OPERATOR, URL, _stuck  # noqa: F401


def test_answered_event_passes_the_fleet_audit_filter(core_client):
    """D-407 re-run B: Fleet's event store refused `token_id` as a credential key."""
    client, services, stuck_id = _stuck(core_client)
    seen = []
    services.events.subscribe(lambda event: seen.append(event))
    client.post(URL, json={"stuck_id": "stuck-old", "decision": "WAIT"}, headers=OPERATOR)
    client.post(URL, json={"stuck_id": stuck_id, "decision": "BACK_AND_RETRY"}, headers=OPERATOR)
    client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=OPERATOR)
    stuck_events = [e for e in seen if e.type.startswith("nav.line_stuck_")]
    assert stuck_events
    for event in stuck_events:
        assert not core_event_store._contains_sensitive_field(event.model_dump(mode="json")), event.type
