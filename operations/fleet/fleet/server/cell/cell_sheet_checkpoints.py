"""Durable manual-sheet barriers in the existing Fleet journal; access remains unavailable."""

import hashlib
import json
import math
from .mission_store import MissionConflict

REASON = "OPERATOR_SHEET_ACCESS_UNAVAILABLE"
_FIELDS = {"checkpoint_id", "kind", "before_transfer_ordinal", "pallet_id", "layer_index",
           "sheet_pose_base", "thickness_m"}


def migrate(connection):
    version = connection.execute("SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_sheet_checkpoints'").fetchone()[0]
    if version is not None and version > 1:
        raise RuntimeError("unsupported Cell sheet checkpoint migration version")
    connection.execute("""CREATE TABLE IF NOT EXISTS fleet_cell_checkpoints (
        mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
        checkpoint_id TEXT NOT NULL,
        before_transfer_ordinal INTEGER NOT NULL CHECK(before_transfer_ordinal > 0),
        descriptor_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('WAITING', 'WAITING_ACCESS')),
        updated_at TEXT NOT NULL,
        PRIMARY KEY(mission_id, checkpoint_id), UNIQUE(mission_id, before_transfer_ordinal))""")
    connection.execute("INSERT OR IGNORE INTO fleet_component_migrations(component,version,applied_at) "
                       "VALUES('cell_sheet_checkpoints',1,strftime('%Y-%m-%dT%H:%M:%fZ','now'))")


def insert(connection, mission_id, submission, now):
    expected = _canonical_checkpoints(submission)
    if "operator_checkpoints" not in submission:
        if expected:
            raise ValueError("manual Job requires its complete operator checkpoint projection")
        return
    checkpoints = submission["operator_checkpoints"]
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ValueError("operator_checkpoints must be a nonempty canonical list")
    previous = 0
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict) or set(checkpoint) != _FIELDS:
            raise ValueError("invalid operator checkpoint descriptor")
        ordinal = checkpoint["before_transfer_ordinal"]
        layer = checkpoint["layer_index"]
        if (type(ordinal) is not int or not previous < ordinal <= len(submission["steps"])
                or type(layer) is not int or layer < 0 or checkpoint["kind"] != "operator_sheet"):
            raise ValueError("operator checkpoint ordinal, layer or kind is invalid")
        previous = ordinal
        pallet = checkpoint["pallet_id"]
        if not isinstance(pallet, str) or not pallet.strip() or pallet != pallet.strip() or len(pallet) > 192:
            raise ValueError("operator checkpoint pallet is invalid")
        pose = checkpoint["sheet_pose_base"]
        values = [] if not isinstance(pose, dict) else list(pose.values())
        if (not isinstance(pose, dict) or set(pose) != {"x_m", "y_m", "z_m", "yaw_rad"}
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or type(checkpoint["thickness_m"]) not in (int, float)
                or not math.isfinite(checkpoint["thickness_m"]) or checkpoint["thickness_m"] <= 0):
            raise ValueError("operator checkpoint pose or thickness is invalid")
        next_box = submission["steps"][ordinal - 1]["inputs"]
        if (next_box.get("item"), next_box.get("pallet_id"), next_box.get("layer_index")) != ("box", pallet, layer):
            raise ValueError("operator checkpoint does not precede its matching box layer")
        unsigned = {key: value for key, value in checkpoint.items() if key != "checkpoint_id"}
        digest = _digest(submission, unsigned)
        if checkpoint["checkpoint_id"] != digest:
            raise ValueError("operator checkpoint identity does not match its documents and instruction")
        connection.execute("INSERT INTO fleet_cell_checkpoints VALUES(?,?,?,?,'WAITING',?)",
                           (mission_id, digest, ordinal, json.dumps(checkpoint, allow_nan=False), now))
    if checkpoints != expected:
        raise ValueError("operator checkpoint projection differs from the complete canonical manual Job")


def _digest(submission, descriptor):
    bound = {"recipe_sha256": submission["recipe_digest"], "cell_sha256": submission["cell_digest"],
             "checkpoint": descriptor}
    return hashlib.sha256(json.dumps(bound, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _canonical_checkpoints(submission):
    job = submission["job"]
    raw_steps = job.get("steps", []) if isinstance(job, dict) else []
    if not isinstance(raw_steps, list):
        raise ValueError("manual Job steps must be a list")
    if not any(isinstance(step, dict) and step.get("kind") == "operator_sheet" for step in raw_steps):
        return []  # Existing fake and robot-only Jobs retain their original shape.
    if (job.get("recipe_hash"), job.get("cell_hash")) != (submission["recipe_digest"], submission["cell_digest"]):
        raise ValueError("manual Job document hashes do not match checkpoint documents")
    expected, picks, pending = [], 0, None
    for step in raw_steps:
        if not isinstance(step, dict):
            raise ValueError("manual Job contains a malformed step")
        kind = step.get("kind")
        identity = (step.get("item"), step.get("pallet"), step.get("layer"))
        if kind == "operator_sheet":
            if (pending is not None or set(step) != {"kind", "item", "pallet", "layer", "target", "approach_z", "thickness_m"}
                    or step["item"] != "slip_sheet" or step["approach_z"] is not None):
                raise ValueError("manual sheet step has invalid fields or splits a transfer")
            pose = step["target"]
            if not isinstance(pose, dict) or set(pose) != {"x", "y", "z", "yaw"}:
                raise ValueError("manual sheet checkpoint target is invalid")
            descriptor = {"kind": "operator_sheet", "before_transfer_ordinal": picks + 1,
                          "pallet_id": step["pallet"], "layer_index": step["layer"],
                          "sheet_pose_base": {"x_m": pose["x"], "y_m": pose["y"], "z_m": pose["z"], "yaw_rad": pose["yaw"]},
                          "thickness_m": step["thickness_m"]}
            expected.append({"checkpoint_id": _digest(submission, descriptor), **descriptor})
        elif kind == "pick":
            if pending is not None or step.get("item") != "box":
                raise ValueError("manual Job must contain adjacent box transfers")
            pending, picks = identity, picks + 1
        elif kind == "place":
            if pending is None or pending != identity:
                raise ValueError("manual Job transfer pair identity is inconsistent")
            pending = None
        elif kind != "pallet_done" or pending is not None:
            raise ValueError("manual Job contains an unsupported step")
    if pending is not None or picks != len(submission["steps"]):
        raise ValueError("manual Job transfer count differs from its checkpoint plan")
    return expected


def read(connection, mission_id):
    return [{**json.loads(row["descriptor_json"]), "status": row["status"], "updated_at": row["updated_at"]}
            for row in connection.execute("SELECT * FROM fleet_cell_checkpoints WHERE mission_id=? "
                                          "ORDER BY before_transfer_ordinal", (mission_id,))]


def due(connection, mission_id, step_index):
    return connection.execute("SELECT * FROM fleet_cell_checkpoints WHERE mission_id=? "
                              "AND before_transfer_ordinal<=? ORDER BY before_transfer_ordinal",
                              (mission_id, step_index + 1)).fetchall()


def recover_ready(connection, now, event):
    rows = connection.execute("SELECT * FROM fleet_cell_jobs WHERE status='READY'").fetchall()
    return sum(hold_due(connection, job, job["current_step_index"], now, event) for job in rows)


def guard_ready(connection, mission_id, step_index, now, event):
    if type(step_index) is not int or step_index < 0:
        raise ValueError("step_index must be a non-negative integer")
    job = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
    if job is None:
        raise KeyError(mission_id)
    if job["status"] != "READY" or job["current_step_index"] != step_index:
        raise MissionConflict("only the current READY step may pass checkpoint dispatch guard")
    hold_due(connection, job, step_index, now, event)


def hold_due(connection, job, step_index, now, event):
    rows = due(connection, job["mission_id"], step_index)
    if not rows:
        return False
    if job["status"] == "HOLD" and job["reason"] == REASON and all(row["status"] == "WAITING_ACCESS" for row in rows):
        return True
    connection.execute("UPDATE fleet_cell_checkpoints SET status='WAITING_ACCESS',updated_at=? "
                       "WHERE mission_id=? AND before_transfer_ordinal<=? AND status='WAITING'",
                       (now, job["mission_id"], step_index + 1))
    connection.execute("UPDATE fleet_cell_jobs SET status='HOLD',reason=?,current_step_index=?,updated_at=? WHERE mission_id=?",
                       (REASON, step_index, now, job["mission_id"]))
    connection.execute("UPDATE fleet_cell_steps SET status='HOLD',reason=?,updated_at=? WHERE mission_id=? "
                       "AND step_index=? AND status IN ('WAITING','READY','HOLD')", (REASON, now, job["mission_id"], step_index))
    # Never turn an unresolved physical outcome into a quiet claim.
    connection.execute("UPDATE fleet_action_claims SET phase='HELD',lease_until=NULL WHERE owner_kind='mission' "
                       "AND owner_id=? AND phase='CLAIMED'", (job["mission_id"],))
    event(connection, job["mission_id"], step_index, "CELL_OPERATOR_SHEET_HELD", "fleet",
          {"reason": REASON, "checkpoint_ids": [row["checkpoint_id"] for row in rows]})
    return True
