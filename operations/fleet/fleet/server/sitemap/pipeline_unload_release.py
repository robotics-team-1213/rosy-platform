"""When a Pinky docked at S3 may leave (2026-11-19 panel: Claude, opencode, agy partial; user: "다 가져가고 나면 판정해서
전달하고, 정지해 있던 Pinky가 출발해야 해").

A dock_and_unload_s3 with container_count N makes one unload batch of N chained s3_shuttle tasks. The vehicle is ready
only when every check holds at once:
- COUNT: all N tasks COMPLETED (the ledger), none aborted or cancelled;
- BED: the last completion's source_clearance saw 0 objects on the Pinky site (the cell's camera); missing = not seen;
- ARM: arm_s folded by measurement and fresh; the cell RELEASED and not inhibited;
- HOLD: no arm hold, no person detected or HUMAN_HOLD.
Either source alone fails one way: the camera alone leaves with a box it missed, the ledger alone leaves after a box
fell back on the bed. A named operator still sends the vehicle (depart_s3, 11-14: real motion keeps a person's
approval); a release is used once per batch."""
from __future__ import annotations

from fastapi import HTTPException

FOLD_MAX_AGE_S = 120.0  # an approval may come a minute after the last park; older fold readings are not trusted
MAX_CONTAINERS = 6


def batch_tasks(tasks: dict, robot_id: str) -> list[dict]:
    """The robot's newest unload batch, in order."""
    rows = [t for t in tasks.values() if t.get("unload_batch_id") and t.get("robot_id") == robot_id]
    if not rows:
        return []
    newest = max(rows, key=lambda t: t.get("created_at") or 0)["unload_batch_id"]
    return sorted((t for t in rows if t["unload_batch_id"] == newest), key=lambda t: t.get("unload_index", 0))


def unload_release(state, robot_id: str, *, now: float, human_detected: bool) -> dict:
    """{ready, reasons, ...} for one robot; reasons empty exactly when ready."""
    rows = batch_tasks(state.omx_cell_tasks, robot_id)
    out = {"robot_id": robot_id, "ready": False, "batch_id": None, "expected": 0, "completed": 0, "reasons": []}
    if not rows:
        return {**out, "reasons": ["NO_UNLOAD_BATCH"]}
    batch, expected = rows[0]["unload_batch_id"], int(rows[0].get("unload_expected") or len(rows))
    done = [t for t in rows if t.get("status") == "COMPLETED"]
    reasons = []
    if any(t.get("status") in ("ABORTED", "CANCELLED") for t in rows):
        reasons.append("UNLOAD_ABORTED")
    if len(done) < expected:
        reasons.append("COUNT_MISMATCH")
    last = max(done, key=lambda t: t.get("completed_at") or 0) if done else {}
    clearance = (last.get("stage_result") or {}).get("source_clearance") if isinstance(last.get("stage_result"), dict) else None
    objects = clearance.get("objects") if isinstance(clearance, dict) else None
    if type(objects) is not int:
        reasons.append("BED_NOT_OBSERVED")
    elif objects != 0:
        reasons.append("CARGO_NOT_EMPTY")
    cell = state.omx_cell_states.get("cell_s") or {}
    if cell.get("phase") != "RELEASED" or cell.get("amr_motion_inhibited"):
        reasons.append("CELL_NOT_RELEASED")
    arm = state.arm_live_states.get("arm_s") or {}
    updated = arm.get("updated_at")
    if arm.get("folded") is not True or not isinstance(updated, (int, float)) or now - updated > FOLD_MAX_AGE_S:
        reasons.append("ARM_NOT_HOME")
    if (state.arm_holds.get("arm_s") or {}).get("held"):
        reasons.append("ARM_HELD")
    if human_detected or cell.get("phase") == "HUMAN_HOLD":
        reasons.append("HUMAN_HOLD")
    if batch in state.unload_releases:
        reasons.append("RELEASE_ALREADY_USED")
    return {**out, "ready": not reasons, "batch_id": batch, "expected": expected, "completed": len(done),
            "reasons": reasons, "clearance": clearance, "arm_folded": arm.get("folded"), "arm_updated_at": updated}


def container_count(body: dict) -> int:
    count = body.get("container_count", 1)
    if type(count) is not int or not 1 <= count <= MAX_CONTAINERS:
        raise HTTPException(422, detail={"code": "INVALID_CONTAINER_COUNT"})
    return count


def install_unload_release_routes(app, ctx) -> None:
    import time

    app.state.unload_releases = getattr(app.state, "unload_releases", {})

    @app.get("/api/fleet/pipeline/unload-release", dependencies=ctx.read_guard)
    async def read_unload_release(robot_id: str):
        return unload_release(app.state, robot_id, now=time.time(), human_detected=bool(ctx._is_human_detected()))
