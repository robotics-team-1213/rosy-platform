"""Record the cell's self-resetting A/B cycle as training episodes (D-872 §2.3, scripted teacher).

The box is located with the top camera; the planner turns that into one cycle (A: pick it and place it on
the destination; B: bring it back where it was picked) and record_session --replay records it through the
guard's teacher mode as two LeRobot episodes, in a run folder of its own (a new dataset root, its own
session.json). Each episode is then labelled from what was recorded: while the jaws were commanded closed,
did the follower's jaws stop short of the command (something between them)? That is the runner's grasp
rule, read back from the dataset. After the run the box should be where it was picked again.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_observe import locate  # noqa: E402

EMPTY_MARGIN = 2.0  # jaws this far above their closed command are holding something (chunk_runner's rule)


def episode_outcomes(dataset_root: Path, closed: float) -> list:
    """Per episode: "held" when the jaws stayed short of a closed command, "empty" when they closed, or
    "unknown" when the episode never commanded them closed."""
    import numpy as np
    import pandas as pd

    files = sorted(Path(dataset_root).glob("data/**/*.parquet"))
    if not files:
        return []
    frame = pd.concat(pd.read_parquet(p, columns=["episode_index", "observation.state", "action"]) for p in files)
    out = []
    for episode, rows in frame.groupby("episode_index"):
        state, action = np.stack(rows["observation.state"].to_numpy()), np.stack(rows["action"].to_numpy())
        closing = action[:, 5] <= closed + 0.5
        if not closing.any():
            out.append({"episode": int(episode), "outcome": "unknown", "basis": "the jaws were never commanded closed"})
            continue
        gap = float(np.median(state[closing, 5] - action[closing, 5]))
        out.append({"episode": int(episode), "outcome": "held" if gap > EMPTY_MARGIN else "empty",
                    "basis": f"jaws {gap:+.1f} from their closed command over {int(closing.sum())} frames"})
    return out


def record_cycle(cell, config: dict, calibration: dict, work: Path, source: str = "pinky", dest: str = "belt",
                 run=subprocess.run) -> dict:
    """One recorded A/B cycle. No chunk session may be running: record_session takes the arm."""
    from cell_pipeline import target
    from grasp_planner import Planner

    found = locate(cell, config, calibration, source)
    if not found["found"]:
        return {"result": "not located", "locate": found}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(work) / "recordings" / stamp
    folder.mkdir(parents=True)
    pick = target(config, source, found["arm_m"])  # the site's yaw: what has held so far (cell_choices)
    place = target(config, dest, config["sites"][dest]["place"], place=True)
    trajectory = Planner(dict(config["plan"], pick=pick, place=place)).cycle_trajectory()
    (folder / "cycle.json").write_text(json.dumps(trajectory))
    rec = config["record"]
    record_config = json.loads(Path(rec["config"]).expanduser().read_text())
    root = Path(record_config["dataset"]["root"])
    record_config["dataset"]["root"] = str(root.with_name(f"{root.name}-{stamp}"))  # LeRobot wants a new root
    (folder / "record-config.json").write_text(json.dumps(record_config, indent=2))
    tool = rec.get("session_tool", str(Path(__file__).resolve().with_name("record_session.py")))
    command = [rec.get("python", sys.executable), tool, "--config", str(folder / "record-config.json"),
               "--caps", str(Path(rec["caps"]).expanduser()), "--replay", str(folder / "cycle.json")]
    finished = run(command, cwd=folder)
    session_path = folder / "session.json"
    if not session_path.exists():
        return {"result": "no session record", "exit": finished.returncode, "folder": str(folder)}
    session = json.loads(session_path.read_text())
    outcomes = episode_outcomes(Path(record_config["dataset"]["root"]), float(config["plan"]["grip_closed"]))
    for row in outcomes:
        row["segment"] = "A" if row["episode"] == 0 else "B"
    session["episode_outcomes"] = outcomes or session.get("episode_outcomes")
    session["outcome_source"] = "cell_record: follower jaws against their closed command, read from the dataset"
    session_path.write_text(json.dumps(session, indent=2, default=str))
    back = locate(cell, config, calibration, source)  # the camera services are back after the session
    reset_mm = (1000 * sum((a - b) ** 2 for a, b in zip(back["arm_m"], found["arm_m"])) ** 0.5
                if back["found"] else None)
    ok = (finished.returncode == 0 and session.get("safe_end") is True
          and [o["outcome"] for o in outcomes] == ["held", "held"])
    return {"result": "recorded" if ok else "recorded with issues", "folder": str(folder),
            "dataset": record_config["dataset"]["root"], "exit": finished.returncode,
            "safe_end": session.get("safe_end"), "outcomes": outcomes, "reset_mm": reset_mm,
            "seal": f"record_seal.py --session-dir {folder} --name arm-s-cycle-{stamp} --rig-revision <rig> "
                    "--calibration <follower calibration json>"}
