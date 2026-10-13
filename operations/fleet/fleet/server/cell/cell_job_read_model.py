"""Read-only Cell Job projections; callers retain ownership of their SQLite transaction."""

import json
from . import cell_sheet_checkpoints as sheets


def read_cell_job(connection, mission_id):
    row = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    for source, target in (("job_json", "job"), ("resources_json", "resources"),
                           ("ledger_markers_json", "ledger_markers")):
        job[target] = json.loads(job.pop(source))
    job["steps"] = []
    for step_row in connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? ORDER BY step_index", (mission_id,)):
        step = dict(step_row)
        step["step"] = json.loads(step.pop("step_json"))
        for source, target in (("grant_json", "grant"), ("result_json", "result"),
                               ("goal_evidence_json", "goal_evidence")):
            raw = step.pop(source)
            step[target] = json.loads(raw) if raw is not None else None
        job["steps"].append(step)
    job["events"] = [
        {**dict(event), "detail": json.loads(event["detail_json"])}
        for event in connection.execute("SELECT * FROM fleet_cell_events WHERE mission_id=? ORDER BY event_id", (mission_id,))
    ]
    for event in job["events"]:
        event.pop("detail_json", None)
    checkpoints = sheets.read(connection, mission_id)
    if checkpoints:
        job["operator_checkpoints"] = checkpoints
    return job


def jobs_by_status(connection, status):
    rows = connection.execute("SELECT mission_id FROM fleet_cell_jobs WHERE status=? ORDER BY updated_at, mission_id",
                              (status,)).fetchall()
    return [read_cell_job(connection, row["mission_id"]) for row in rows]


def unresolved_jobs(connection):
    rows = connection.execute(
        "SELECT DISTINCT j.mission_id FROM fleet_cell_jobs j JOIN fleet_action_claims c "
        "ON c.owner_kind='mission' AND c.owner_id=j.mission_id AND c.generation=j.dispatch_generation "
        "WHERE j.status='HOLD' AND c.phase IN ('UNKNOWN', 'DISPATCHING') "
        "ORDER BY j.updated_at, j.mission_id").fetchall()
    return [read_cell_job(connection, row["mission_id"]) for row in rows]
