"""Task-card composition, static-episode verification, and multi-arm pair cleanup helpers for `record_session.py`."""
from __future__ import annotations

import json
import re
import signal
import sys
import time
from pathlib import Path

CARD_SCHEMA = "rosy.omx-task-card.v1"
STATIC_RANGE = 1.0  # largest per-joint action range (LeRobot units) that still counts as an untouched leader


def interrupt_on_parent_death() -> None:
    """In the recorder (Linux): SIGINT when this wrapper dies, so it never runs on unsupervised."""
    import ctypes

    PR_SET_PDEATHSIG = 1
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGINT)


RUNNER_HOLD_EXIT = 75  # record_session ended but left chunk_runner holding torque ON: a person must act
RUNNER_KILLED_EXIT = 76  # chunk_runner was unresponsive and killed; torque was not cut, the fold is unconfirmed
RUNNER_UNCONFIRMED_EXIT = 77  # the runner died by a signal, or its state could not be checked: no fold confirmed
LEFT_KEYS = ("runner_held", "runner_killed", "runner_unconfirmed")  # record keys: finish() must not cut torque
RUNNER_SILENT_S = 15.0  # alive, yet no chunk-status.jsonl, live.json or hold.json write for this long: unresponsive


class RunnerLeftArm(Exception):
    """The runner ended its part without a confirmed fold: the session must not cut torque or restore caps."""
    key = "runner_left"


class RunnerHeld(RunnerLeftArm):
    """chunk_runner reported an interrupt HOLD (or its state could not be read): torque ON at its pose."""
    key = "runner_held"


class RunnerUnresponsive(RunnerLeftArm):
    """chunk_runner was killed after RUNNER_SILENT_S of silence: torque as the motors hold it, the pose unknown."""
    key = "runner_killed"


class RunnerUnconfirmed(RunnerLeftArm):
    """No fold confirmation: the runner ended by a signal (e.g. -9), or the interrupt handling itself failed."""
    key = "runner_unconfirmed"


def wait_for_runner(child, io: Path, offset: int, *, silent_s=RUNNER_SILENT_S, clock=time.monotonic, sleep=time.sleep):
    """After SIGINT to chunk_runner: ("exited", code) once it ended (folded, released or guard-stopped), ("hold", row)
    on its HOLD (a status row after `offset`, or hold.json naming this child's pid, so one written before the signal
    counts too) or when its state cannot be read, and ("silent", None) only when the child is alive and none of
    chunk-status.jsonl, live.json and hold.json changed for silent_s."""
    status, live, hold = (Path(io) / name for name in ("chunk-status.jsonl", "live.json", "hold.json"))
    seen, quiet_since, buffer = None, clock(), b""
    while True:
        code = child.poll()
        if code is not None:
            return "exited", code
        try:
            for path, mark in ((hold, "hold"), (live, "interrupt")):  # this runner's own HOLD marks, by pid
                if path.exists():
                    row = json.loads(path.read_text() or "{}")
                    if isinstance(row, dict) and row.get("pid") == getattr(child, "pid", None) and row.get(mark) in (True, "hold"):
                        return "hold", row
            if status.exists():
                with status.open("rb") as f:
                    f.seek(offset)
                    data = f.read()
                offset += len(data)
                buffer += data
                *done, buffer = buffer.split(b"\n")
                for line in done:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("command") == "interrupt" and row.get("hold"):
                        return "hold", row
            stamp = tuple(p.stat().st_mtime_ns if p.exists() else None for p in (status, live, hold)) + (offset,)
        except (OSError, ValueError) as error:  # cannot tell: treat as a possible HOLD, never start finish()
            return "hold", {"hold": True, "error": f"runner state unreadable: {type(error).__name__}: {error}"[:300]}
        if stamp != seen:
            seen, quiet_since = stamp, clock()
        elif clock() - quiet_since >= silent_s:
            return "silent", None
        sleep(0.5)


def runner_left_arm(session, record: dict, follower) -> None:
    """Instead of finish(): no torque write, no cap restore. A killed runner gets a read-only torque readback."""
    left = next(record[k] for k in LEFT_KEYS if record.get(k))
    if not record.get("runner_held") and not left.get("runner_alive"):  # the bus is free: read torque, write nothing
        def read(bus):
            out = {}
            for motor in follower:
                bus.motor = motor
                try:
                    out[motor] = bus.cleanup_read("torque")
                except Exception as exc:  # noqa: BLE001
                    out[motor] = f"error: {exc}"
            return out

        try:
            record["torque_readback"] = session._with_follower(read)
        except Exception as exc:  # noqa: BLE001
            record["torque_readback"] = {"open": f"error: {exc}"}
    record["manual_attention_required"] = True
    session.log(step=next(k for k in LEFT_KEYS if record.get(k)).upper(), report=left,
                torque_readback=record.get("torque_readback"),
                action="torque not cut and caps not restored: a person supports the arm"
                       + (", then kill -USR2 the runner" if record.get("runner_held") else ""))


def release(anchor_file: str | Path = __file__) -> str | None:
    """The code commit these tools came from (RELEASE written by omx_autoupdate.py), if installed so."""
    marker = Path(anchor_file).resolve().parents[3] / "RELEASE"
    return marker.read_text().strip() if marker.exists() else None


def load_task_card(path: Path) -> dict:
    import yaml

    card = yaml.safe_load(path.read_text(encoding="utf-8"))
    record = card.get("record") if isinstance(card, dict) else None
    if not isinstance(card, dict) or card.get("schema") != CARD_SCHEMA or not isinstance(record, dict):
        raise SystemExit(f"task card needs schema {CARD_SCHEMA} and a record block")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(card.get("task_id", ""))):
        raise SystemExit("task_id must be a lowercase slug")
    if type(card.get("revision")) is not int or card["revision"] < 1:
        raise SystemExit("revision must be a positive integer")
    if not isinstance(card.get("single_task"), str) or not card["single_task"].strip():
        raise SystemExit("single_task text is required")
    if not str(record.get("root_prefix", "")).startswith("/"):
        raise SystemExit("record.root_prefix must be an absolute path")
    for key in ("episode_time_s", "reset_time_s", "num_episodes"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise SystemExit(f"record.{key} must be positive")
    return card


def compose(config: dict, card: dict, *, stamp: str) -> dict:
    """The device config with the card's task plugged into its dataset section (config is not changed)."""
    record = card["record"]
    dataset = {
        **config["dataset"],
        "single_task": card["single_task"],
        "episode_time_s": record["episode_time_s"],
        "reset_time_s": record["reset_time_s"],
        "num_episodes": record["num_episodes"],
        "root": f"{record['root_prefix'].rstrip('/')}/{card['task_id']}-r{card['revision']}-{stamp}",
    }
    if "repo_id" in record:
        dataset["repo_id"] = record["repo_id"]
    return {**config, "dataset": dataset}


def static_episodes(root: Path, threshold: float = STATIC_RANGE) -> dict:
    """Episodes whose leader action never moved beyond `threshold` on any joint. 2026-10-24: ten
    recorded episodes had range 0.0 because nobody held the leader. Listed in static_episodes.json;
    a dataset with no moving episode also gets DO_NOT_TRAIN.txt."""
    import numpy as np
    import pandas as pd

    static, total = [], 0
    for path in sorted(root.glob("data/**/*.parquet")):
        frame = pd.read_parquet(path, columns=["episode_index", "action"])
        for episode, rows in frame.groupby("episode_index"):
            total += 1
            action = np.stack(rows["action"].to_numpy())
            if float((action.max(0) - action.min(0)).max()) <= threshold:
                static.append(int(episode))
    result = {"episodes": total, "static": static, "threshold": threshold}
    if static:
        (root / "static_episodes.json").write_text(json.dumps(result, indent=2))
    if total and len(static) == total:
        (root / "DO_NOT_TRAIN.txt").write_text(
            f"every episode is static (leader action range <= {threshold}); "
            "the leader was not moved - do not train on this dataset\n"
        )
    return result


def build_session_command(
    config_path: Path,
    teleop_only: bool,
    *,
    body_only: bool = False,
    replay: dict | None = None,
    anchor_file: str | Path = __file__,
) -> list:
    """Build the guarded native CLI command (`guarded_native.py` or `bi_omx_follower` native)."""
    if body_only and not teleop_only:
        raise ValueError("body-only mode is manual teleoperation only")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    bi_script = "bimanual" + "_native.py"
    script = bi_script if config["robot"]["type"] == "bi_omx_follower" else "guarded_native.py"
    if replay is not None and (script != "guarded_native.py" or teleop_only or body_only):
        raise ValueError("replay is a one-arm recording")
    runner = [sys.executable, str(Path(anchor_file).with_name(script))]
    if script == bi_script:
        for section in ("robot", "teleop"):
            for arm in ("arm_a", "arm_b"):
                config[section][arm].pop("type", None)
        native = config_path.with_name(config_path.stem + ".native.json")
        native.write_text(json.dumps(config, indent=2))
        config_path = native
    if replay is not None:
        (a0, a1), (r0, r1) = replay["segments"]["A"], replay["segments"]["reset"]
        config["teleop"] = {"type": "rosy_replay", "id": "rosy_replay", "trajectory": replay["path"]}
        config["dataset"] = {
            **config["dataset"],
            "num_episodes": 2,
            "episode_time_s": (a1 - a0) / replay["fps"],
            "reset_time_s": (r1 - r0) / replay["fps"],
        }
        path = config_path.with_name(config_path.stem + ".replay.json")
        path.write_text(json.dumps(config, indent=2))
        return [*runner, "record", "--teacher", f"--config_path={path}"]
    if not teleop_only:
        return [*runner, "record", f"--config_path={config_path}"]
    teleop = config_path.with_name(config_path.stem + ".teleop.json")
    teleop.write_text(
        json.dumps(
            {
                "robot": config["robot"],
                "teleop": config["teleop"],
                "fps": config["dataset"]["fps"],
                "display_data": False,
            },
            indent=2,
        )
    )
    return [*runner, "teleoperate", f"--config_path={teleop}", *(["--body-only"] if body_only else [])]


def finish_pair_sessions(owner_session, record: dict, stopped: list, pairs: dict) -> None:
    """Turn off both followers before any disconnected USB consumes retry deadline, then finish each pair."""
    record["initial_torque_off"] = {}
    for name, session in pairs.items():
        try:
            record["initial_torque_off"][name] = session._with_follower(session.all_torque_off)
        except Exception as exc:
            record["initial_torque_off"][name] = str(exc)
    leader_errors = []
    for name, session in pairs.items():
        try:
            bus = session.open_bus("leader")
            try:
                for motor in range(1, 7):
                    bus.motor = motor
                    try:
                        bus.cleanup_write("torque", 0)
                        session.note_fault(bus, leader=True)
                        if bus.cleanup_read("torque") != 0:
                            raise RuntimeError("torque OFF readback mismatch")
                    except Exception as exc:
                        leader_errors.append(f"{name} leader {motor}: {exc}")
            finally:
                bus.close()
        except Exception as exc:
            leader_errors.append(f"{name} leader: {exc}")
    record["pairs"] = {}
    for name, session in pairs.items():
        state = record["pairs"][name] = {}
        try:
            session.finish(state, [])
        except Exception as exc:
            state.update(safe_end=False, cleanup_error=str(exc))
    for unit in stopped:
        try:
            owner_session.systemctl("start", unit)
        except Exception as exc:
            record.setdefault("service_errors", []).append(f"{unit}: {exc}")
    record["restarted_services"] = stopped
    record["leader_torque_errors"] = leader_errors
    record["safe_end"] = not leader_errors and all(
        state.get("safe_end") and state.get("leader_gripper_torque_after") == 0
        for state in record["pairs"].values()
    )
    record["ended"] = time.time()
    owner_session.log(step="session", **record)
