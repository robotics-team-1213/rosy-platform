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
    """Build the guarded native CLI command (`guarded_native.py` or `bimanual_native.py`)."""
    if body_only and not teleop_only:
        raise ValueError("body-only mode is manual teleoperation only")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    script = "bimanual_native.py" if config["robot"]["type"] == "bi_omx_follower" else "guarded_native.py"
    if replay is not None and (script != "guarded_native.py" or teleop_only or body_only):
        raise ValueError("replay is a one-arm recording")
    runner = [sys.executable, str(Path(anchor_file).with_name(script))]
    if script == "bimanual_native.py":
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
