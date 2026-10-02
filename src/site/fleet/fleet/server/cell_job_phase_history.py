"""Validate phase evidence against the durable history of a Cell attempt."""

import json

from .mission_store import MissionConflict

_ALLOWED_NEXT = {
    "SUBMITTING": {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "ACCEPTED": {"RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "RUNNING": {"CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
    "CANCEL_REQUESTED": {"UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
}


def verify_cell_phase_history(connection, mission_id, step_index, receipt):
    rows = connection.execute(
        "SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
        "AND event_type='CELL_STEP_ACTION_READBACK' ORDER BY event_id",
        (mission_id, step_index),
    ).fetchall()
    identities, latest = {}, {}
    for row in rows:
        document = json.loads(row["detail_json"])
        for phase in document["phase_summaries"]:
            ordinal, event_id = phase["ordinal"], phase["journal_event_id"]
            identities[(ordinal, event_id)] = phase
            if ordinal not in latest or event_id > latest[ordinal]["journal_event_id"]:
                latest[ordinal] = phase
    for phase in receipt["phase_summaries"]:
        ordinal, event_id = phase["ordinal"], phase["journal_event_id"]
        prior_identity = identities.get((ordinal, event_id))
        if prior_identity is not None and prior_identity != phase:
            raise MissionConflict("Cell phase event contains different evidence")
        previous = latest.get(ordinal)
        if previous is not None:
            if event_id <= previous["journal_event_id"]:
                continue
            allowed = _ALLOWED_NEXT.get(previous["state"])
            if allowed is None or (phase["state"] != previous["state"] and phase["state"] not in allowed):
                raise MissionConflict("Cell phase receipt regresses or changes a terminal phase")
        if ordinal > 0 and (ordinal - 1 not in latest or latest[ordinal - 1]["state"] != "SUCCEEDED"):
            raise MissionConflict("Cell phase receipt skips an unconfirmed prior phase")
        latest[ordinal] = phase
    if receipt["state"] == "SUCCEEDED" and (
            set(latest) != {0, 1, 2, 3} or any(phase["state"] != "SUCCEEDED" for phase in latest.values())):
        raise MissionConflict("Cell success contradicts the latest durable phase evidence")
