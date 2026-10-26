"""Read-only Cell Job projections; callers retain ownership of their SQLite transaction.

The single-arm dispatcher's queries (``jobs_by_status``, ``unresolved_jobs``) never return a
multi-arm Job (D-779 stages 2-4): ``cell_arm_dispatcher`` drives those.
"""

import json
from . import cell_arm_jobs, cell_sheet_checkpoints as sheets

_SINGLE_ARM = "mission_id NOT IN (SELECT mission_id FROM fleet_cell_arm_jobs)"


def read_cell_job(connection, mission_id):
    row = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
    if row is None or row["provenance_kind"] != "legacy":
        return None
    job = dict(row)
    job.pop("provenance_kind")
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
    cell_arm_jobs.attach(connection, job)
    return job


def jobs_by_status(connection, status):
    rows = connection.execute(f"SELECT mission_id FROM fleet_cell_jobs WHERE provenance_kind='legacy' "
                              f"AND status=? AND {_SINGLE_ARM} "
                              "ORDER BY updated_at, mission_id", (status,)).fetchall()
    return [read_cell_job(connection, row["mission_id"]) for row in rows]


def unresolved_jobs(connection):
    rows = connection.execute(
        "SELECT DISTINCT j.mission_id FROM fleet_cell_jobs j JOIN fleet_action_claims c "
        "ON c.owner_kind='mission' AND c.owner_id=j.mission_id AND c.generation=j.dispatch_generation "
        f"WHERE j.provenance_kind='legacy' AND j.status='HOLD' "
        f"AND c.phase IN ('UNKNOWN', 'DISPATCHING') AND j.{_SINGLE_ARM} "
        "ORDER BY j.updated_at, j.mission_id").fetchall()
    return [read_cell_job(connection, row["mission_id"]) for row in rows]
