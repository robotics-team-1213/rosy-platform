"""Two-arm policy entry: each arm takes the reviewed single-arm `entry` chunk from home to its canonical start before any policy chunk.

Reuses cell_policy_entry (validate_entry_chunk, run_entry_chunk, entry_ready) and the StateGate verdicts exactly as the
single-arm paths do. The arms go one after the other (arm a, then arm b), each admitted through TwoArmChunkGuard like a
policy chunk, so no concurrent entry motion exists that the guard has not cleared. Any failure latches the guard, sends
human-hold to both arms (an arm that stands extended keeps torque) and returns without a policy command. A dry run sends
nothing: it validates the chunks and clears them through the guard.
"""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable, Mapping

from cell_policy_entry import ENTRY_START_TOL, empty_gripper_ok, entry_ready, max_diff, pose6, run_entry_chunk, valid_state, validate_entry_chunk
from cell_policy_timing import send_hold
from cell_two_arm_guard import ARMS, TwoArmChunkGuard

SCHEMA = "rosy.omx-two-arm-entry.v1"


def _hold_both(cells: Mapping[str, Any], log: Callable[[dict[str, Any]], Any]) -> dict[str, bool]:
    out = {}
    for arm in ARMS:
        try:
            send_hold(cells[arm], log=lambda row, _a=arm: log({"arm": _a, **row}))
            out[arm] = True
        except Exception:
            out[arm] = False
    return out


def run_two_arm_entry(
    cells: Mapping[str, Any], libraries: Mapping[str, Mapping[str, Any]], guard: TwoArmChunkGuard, work_dir: Path, *,
    authorizers: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    jaw_specs: Mapping[str, Mapping[str, Any] | None] | None = None,
    kins: Mapping[str, Any] | None = None,
    state_gates: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    log: Callable[[dict[str, Any]], Any] = lambda _row: None,
) -> dict[str, Any]:
    """Entry for every arm whose library has an `entry` chunk. result: entered | dry_run | no_entry | refused | fault.

    `entry_end` per arm is the chunk's last frame; a dry run returns it so the caller can seed a passive cell with it."""
    if not dry_run and (authorizers is None or set(authorizers) != set(ARMS)):
        raise ValueError("live entry requires per-arm D-911 authorizers")
    events: list[dict[str, Any]] = []

    def emit(row: dict[str, Any]) -> None:
        events.append(row)
        log(row)

    def report(result: str, arms: dict, reason: str | None = None, holds: dict | None = None) -> dict[str, Any]:
        return {"schema": SCHEMA, "result": result, "reason": reason, "dry_run": dry_run, "arms": arms, "holds": holds, "events": events}

    def stop(arms: dict, arm: str, result: str, reason: str) -> dict[str, Any]:
        reason = f"{arm}:entry:{reason}"
        guard.latch_stop(reason)
        emit({"arm": arm, "event": "entry_stopped", "reason": reason})
        holds = None if dry_run else _hold_both(cells, lambda row: emit({"event": "hold", **row}))
        arms[arm] = {**arms.get(arm, {}), "outcome": result}
        return report(result, arms, reason, holds)

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    arms: dict[str, dict[str, Any]] = {}
    entries: dict[str, list[list[float]]] = {}
    for arm in ARMS:  # validate both before either moves
        try:
            frames = validate_entry_chunk(dict(libraries[arm]), (kins or {}).get(arm), (jaw_specs or {}).get(arm))
        except ValueError as exc:
            return stop(arms, arm, "refused", str(exc))
        if frames is None:
            arms[arm] = {"outcome": "no_entry"}
        else:
            entries[arm] = frames
    if not entries:
        return report("no_entry", arms)

    for arm in ARMS:  # the guard needs both poses before the first admission
        try:
            reply = cells[arm].act("state")
        except Exception as exc:
            return stop(arms, arm, "fault", f"state read failed: {exc}")
        ok, _, err = valid_state(reply) if isinstance(reply, dict) else (False, False, "bad reply")
        if ok:
            guard.update_pose(arm, reply["state"], holding=bool(reply.get("holding", False)))
        elif not dry_run:
            return stop(arms, arm, "fault" if isinstance(reply, dict) and reply.get("fault") else "refused", err or "state unavailable")
        else:
            home = pose6(libraries[arm]["chunks"]["home"][-1])
            if home is None:
                return stop(arms, arm, "refused", "no home pose to stand in for the dry-run state")
            guard.update_pose(arm, home)

    for arm in ARMS:
        if arm not in entries:
            continue
        lib, cell, gate, frames = libraries[arm], cells[arm], (state_gates or {}).get(arm), entries[arm]
        entry_pose = frames[-1]
        arms[arm] = {"outcome": "pending", "entry_end": list(entry_pose)}
        if not dry_run:
            status = cell.act("state")
            ok, _, err = valid_state(status)
            if not ok:
                return stop(arms, arm, "fault" if isinstance(status, dict) and status.get("fault") else "refused", err or "state unavailable")
            if gate is not None and (why := gate.roll_error(status["state"])):
                return stop(arms, arm, "refused", why)
            home = pose6(lib["chunks"]["home"][-1])
            if home is None or max_diff(status["state"], home, 5) > ENTRY_START_TOL or not empty_gripper_ok(status, now=time.time()):
                return stop(arms, arm, "refused", "START_POSE_OFF_HOME: arm off home; run home stage first")
            guard.update_pose(arm, status["state"], holding=False)
        admitted = guard.admit_chunk(arm, frames, holding=False)
        if not admitted.get("admitted"):
            return stop(arms, arm, "refused", f"guard:{admitted.get('reason', 'refused')}")
        final_pose: list[float] = list(status["state"]) if not dry_run else list(libraries[arm]["chunks"]["home"][-1])
        try:
            if dry_run:
                final_pose = list(entry_pose)
                arms[arm]["outcome"] = "dry_run"
                emit({"arm": arm, "event": "entry_dry_run_admitted", "admitted": admitted})
                continue
            jaw = (jaw_specs or {}).get(arm)
            _ran, _prefix, err_row = run_entry_chunk(
                cell, dict(lib), work, status, authorizers[arm], lambda row, _a=arm: emit({"arm": _a, **row}),
                jaw_gate=dict(jaw) if jaw is not None else None,
            )
            if err_row is not None:  # run_entry_chunk already sent human-hold to this arm on a load or run fault
                return stop(arms, arm, err_row["result"], str(err_row["reason"]))
            post = cell.act("state")
            if not isinstance(post, dict) or not entry_ready(post, entry_pose):
                return stop(arms, arm, "refused", "POST_ENTRY_STATE_MISMATCH: arm not settled at entry pose with empty gripper")
            final_pose = list(post["state"])
            if gate is not None and (why := gate.verdict(post["state"], after_entry=True)):
                return stop(arms, arm, "refused", why)
            arms[arm]["outcome"] = "entered"
            emit({"arm": arm, "event": "entry_done", "admitted": admitted})
        except Exception as exc:  # an I/O or authorizer error mid-entry: stop both like any other entry failure
            return stop(arms, arm, "fault", f"{type(exc).__name__}: {exc}")
        finally:
            guard.release_chunk(arm, final_pose=final_pose, holding=False)
    return report("dry_run" if dry_run else "entered", arms)
