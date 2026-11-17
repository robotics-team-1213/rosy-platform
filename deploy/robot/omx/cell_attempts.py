#!/usr/bin/env python3
"""One row per pick-and-place attempt, passed or not, with the context that decided it (D-872 §7).

cases.jsonl keeps only the checks that did not pass (the decision model's cases), so it has no
denominator: on 2026-10-25 arm S grasped near the start and missed elsewhere, and nothing could say
how often at which box position, under which map or which ledger values. attempts.jsonl answers that:
each row joins the box estimate (pixel, arm point, sigma, frames), the plan, every chunk's status
(sent target, measured joints, jaw current), the outcome with the stage and class it failed at, and
the code, config, map and choices it ran with. Receipts, cases and frames stay where they are; a row
names its attempt_id, and case rows carry the same id.

  rosy.omx-cell-attempt.v1: {"schema", "attempt_id", "run_id", "t_start", "t_end", "from", "to", "attempt",
      "context": {"code", "config_sha", "plan_sha", "calibration", "choices_used", "choices_sha", "knowledge_sha"},
      "task_binding" (optional Fleet correlation, never a completion verdict),
      "episode" (optional, rows before 2026-11-14 have none): {"id": episode folder name, "path", "sha": digest of
          its ticks.jsonl + result.json at record time}; the folder's task.json names this attempt_id back,
          cell_attempt_episodes.py joins the two,
      "scenario_id", "execution": {"segment", "purpose", "executor", "candidates", "propensity", "outcome"},
      "locate", "grasp_yaw", "plan", "transfer", "verify", "outcome", "fail_stage", "fail_class"}

  cell_attempts.py summary attempts.jsonl [--bin-mm 10]     # success by box position, map and failure
  cell_attempts.py summary --receipts cell-pipeline/receipts # the same from receipts written before this
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "rosy.omx-cell-attempt.v1"
_CODE_NAME = Path(__file__).resolve().parents[3].name
RUN = {"path": None, "run_id": None, "n": 0, "pending": None, "knowledge_sha": None, "params_sha": None,
       "arm_id": "arm_s", "task_binding": None, "episode": None}  # set by the owner entrypoint: one run per process


def _fsync_directory(path: Path) -> None:
    """Make new intent and ledger names durable before acting on their contents."""
    if sys.platform != "linux":
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def start(path: Path, run_id: str | None = None, knowledge: str | None = None, params: str | None = None,
          arm_id: str = "arm_s", task_id: str | None = None, handoff_lease_id: str | None = None) -> None:
    """knowledge: the cell-knowledge file this run's seat reads; params: the cell-params file (None = the shipped
    defaults). Both digests go into every row's context."""
    import cell_params

    if bool(task_id) != bool(handoff_lease_id):
        raise ValueError("task_id and handoff_lease_id must be supplied together")
    binding = {"task_id": task_id, "handoff_lease_id": handoff_lease_id} if task_id else None
    sha = None
    if knowledge:
        import cell_knowledge

        sha = cell_knowledge.load(knowledge)["sha"]
    RUN.update(path=Path(path), run_id=run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), n=0, pending=None,
               knowledge_sha=sha, params_sha=cell_params.load(params)["sha"], arm_id=arm_id,
               task_binding=binding)  # two arms will share a cell


def begin(config: dict, envelope: dict) -> None:
    """An exclusive durable intent survives a crash before the completed attempt row."""
    if RUN["path"] is None:
        if envelope["mode"] == "commissioning":
            return  # an unrecorded supervised probe cannot become reviewed evidence
        raise OSError("no active attempt ledger")
    path = Path(RUN["path"])
    if envelope["mode"] == "automatic" and path.resolve() != (Path(config["work_dir"]).expanduser() / "attempts.jsonl").resolve():
        raise OSError("active attempt ledger differs from the reviewed pipeline")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".pending.json").open("x", encoding="utf-8") as stream:
        json.dump({"attempt_id": f"{RUN['run_id']}-{RUN['n'] + 1:03d}", "envelope": envelope,
                   "task_binding": RUN["task_binding"]}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    RUN["pending"] = f"{RUN['run_id']}-{RUN['n'] + 1:03d}"


_DIGEST_CACHE = {}  # id(dict) -> (repr, sha), 64 entries; guard: an id reuse with a different repr misses


def digest(value) -> str:
    if isinstance(value, dict):
        guard = repr(value)
        hit = _DIGEST_CACHE.get(id(value))
        if hit is not None and hit[0] == guard:
            return hit[1]
        sha = hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]
        if len(_DIGEST_CACHE) >= 64:
            _DIGEST_CACHE.clear()
        _DIGEST_CACHE[id(value)] = (guard, sha)
        return sha
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def context(config: dict, calibration: dict, site: str, choices=None) -> dict:
    record = (calibration or {}).get("sites", {}).get(site)
    return {
        # the cell runs from a test copy named after its commit (~/rosy-test/omx-tools-<sha>)
        "code": _CODE_NAME,
        "config_sha": digest({k: v for k, v in config.items() if k not in ("profiles", "plan", "params")}),
        "plan_sha": digest(config.get("plan")),
        "calibration": None if record is None else {
            "key": site, "coarse": "z_view" in record, "loo_error_mm": record.get("loo_error_mm"),
            "points": len(record.get("points", [])), "measured": record.get("measured"), "sha": digest(record)},
        "choices_used": None if choices is None else
        {name: choices.best(name) for name in sorted(choices.data["values"])},
        "choices_sha": None if choices is None else digest(choices.data["values"]),
        "knowledge_sha": RUN["knowledge_sha"],
        "params_sha": RUN["params_sha"],
        "arm_id": RUN["arm_id"],
    }


def classify(tried: dict) -> tuple[str, str | None, str | None]:
    """(outcome, the stage it failed at, why) from one move() attempt."""
    if tried.get("fail"):  # a stage outside move() (cell_auto_pick: calibrate, choose) names its own failure
        return "failed", tried["fail"]["stage"], tried["fail"]["class"]
    if not tried["locate"].get("found"):
        return "failed", "locate", "box not seen"
    if "plan_error" in tried:
        return "failed", "plan", "no IK for the located box"
    envelope = tried.get("envelope") or (tried.get("transfer") or {}).get("envelope") or {}
    if envelope.get("allowed") is False:
        started = any(not s["command"].startswith("load ") for s in (tried.get("transfer") or {}).get("steps", []))
        return "failed" if started else "held", "envelope", envelope.get("reason")
    moved = tried.get("transfer") or {}
    result, at = moved.get("result"), moved.get("at")
    if result == "surveyed":
        return "surveyed", None, None
    if result == "placed":
        if (tried.get("verify") or {}).get("verified") is not True:
            return "unverified", "verify", "placement position unverified"
        if (tried.get("verify") or {}).get("inside"):
            return "placed", None, None
        return "failed", "verify", "placed out of the next grasp's reach"
    phase = {"run descend_pick": "approach", "run grasp_pick": "grasp", "run lift_pick": "lift",
             "goto above_place": "carry", "run descend_place": "place", "run release_place": "release",
             "run lift_place": "retreat", "park": "retreat"}.get(at, "transfer")
    return "failed", {"empty": "grasp", "misaligned": "hover"}.get(result, phase), f"{result} at {at}"


def record(config: dict, calibration: dict, source: str, dest: str, attempt: int, tried: dict,
           t_start: float, choices=None) -> str | None:
    """Append one attempt row; returns its id (None when no run was started, e.g. in a bare move())."""
    if RUN["path"] is None:
        return None
    RUN["n"] += 1
    attempt_id = f"{RUN['run_id']}-{RUN['n']:03d}"
    outcome, stage, why = classify(tried)
    opened = RUN.get("episode")  # bound by cell_auto_safety.open_episode to the attempt id it predicted
    episode = None
    if opened and opened["attempt_id"] == attempt_id:
        from cell_attempt_episodes import episode_ref

        episode = episode_ref(opened["folder"])
    row = {"schema": SCHEMA, "attempt_id": attempt_id, "run_id": RUN["run_id"], "t_start": round(t_start, 3),
           "t_end": round(time.time(), 3), "from": source, "to": dest, "attempt": attempt,
           "context": context(config, calibration, source, choices), "task_binding": RUN["task_binding"],
           "episode": episode, **tried,
           "outcome": outcome, "fail_stage": stage, "fail_class": why}
    RUN["path"].parent.mkdir(parents=True, exist_ok=True)
    with RUN["path"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())
    pending = RUN["path"].with_suffix(".pending.json")
    if (RUN.get("pending") == attempt_id and pending.exists()
            and json.loads(pending.read_text(encoding="utf-8")).get("attempt_id") == attempt_id):
        pending.unlink()
        RUN["pending"] = None
    return attempt_id


def finish_area_xyz(config: dict, calibration: dict, directive: dict, assessment: dict,
                    result: dict, steps: list[dict], frames: dict, *, folded_home: bool, home: list,
                    t_start: float) -> str:
    """Journal one AreaXYZ trial; retain its intent whenever the arm is not proven home."""
    path = RUN.get("path")
    binding = RUN.get("task_binding")
    if path is None or not isinstance(binding, dict) or RUN.get("pending") is None:
        raise OSError("AreaXYZ attempt has no bound pending intent")
    path = Path(path)
    if path.resolve() != (Path(config["work_dir"]).expanduser() / "attempts.jsonl").resolve():
        raise OSError("AreaXYZ attempt ledger differs from cell work directory")
    pending_path = path.with_suffix(".pending.json")
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OSError("AreaXYZ pending intent unreadable") from exc
    attempt_id = RUN["pending"]
    if (pending.get("attempt_id") != attempt_id or pending.get("task_binding") != binding
            or pending.get("envelope") != assessment
            or directive.get("directive_id") != binding["task_id"] or directive.get("arm_id") != RUN["arm_id"]):
        raise OSError("AreaXYZ pending task or library differs from active attempt")
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if any(json.loads(line).get("attempt_id") == attempt_id for line in existing if line.strip()):
        raise OSError("AreaXYZ attempt row already appended; pending requires manual reconciliation")
    if folded_home:
        from cell_envelope import same_session
        from chunk_runner import SETTLE_TOL

        last = steps[-1] if steps else {}
        seen = last.get("state")
        if (last.get("command") != "park" or last.get("ok") is not True
                or last.get("settled") is not True or not same_session(last, assessment)
                or not isinstance(seen, list) or not isinstance(home, list) or len(seen) != 6 or len(home) != 6
                or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in seen + home)
                or any(abs(a - b) > SETTLE_TOL for a, b in zip(seen[:5], home[:5]))):
            raise OSError("AreaXYZ folded home evidence unavailable")
    outcome = "unverified" if result.get("result") == "unverified_place" else "held"
    if result.get("result") in ("fault", "contact", "slipped_in_transfer"):
        outcome = "failed"
    source = str((directive.get("pick") or {}).get("area") or (directive.get("pick") or {}).get("area_id") or "unknown")
    dest = str((directive.get("place") or {}).get("area") or (directive.get("place") or {}).get("area_id") or "unknown")
    row = {"schema": SCHEMA, "attempt_id": attempt_id, "run_id": RUN["run_id"],
           "t_start": round(t_start, 3), "t_end": round(time.time(), 3), "from": source, "to": dest,
           "attempt": 0, "context": context(config, calibration, source), "task_binding": binding,
           "directive": directive, "envelope": assessment, "transfer": {"result": result.get("result"), "steps": steps},
           "verify": result.get("verification"), "frames": frames,
           "simulation": result.get("simulation"), "outcome": outcome,
           "fail_stage": None if outcome == "unverified" else str(result.get("at") or "transfer"),
           "fail_class": None if outcome == "unverified" else str(result.get("error") or result.get("result")),
           "folded_home": folded_home}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    RUN["n"] += 1
    if folded_home:
        pending_path.unlink()  # after durable terminal row only
        _fsync_directory(path.parent)
        RUN["pending"] = None
    return attempt_id


class ReplanLedger:
    """Close each exact library hash before a supervised hook starts another."""

    def __init__(self, config, calibration, source, dest, attempt, tried, t_start, choices):
        self.config, self.calibration = config, calibration
        self.source, self.dest, self.attempt = source, dest, attempt
        self.tried, self.t_start, self.choices = tried, t_start, choices

    def finish(self, reason, assessment, status, history):
        path = RUN.get("path")
        pending_path = None if path is None else Path(path).with_suffix(".pending.json")
        if (pending_path is None or not pending_path.exists() or RUN.get("pending") is None):
            raise OSError("replan has no durable pending intent")
        try:
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OSError("replan pending intent unreadable") from exc
        if (pending.get("attempt_id") != RUN["pending"]
                or pending.get("envelope", {}).get("library_sha256") != assessment.get("library_sha256")):
            raise OSError("replan pending hash differs from active library")
        row = {**self.tried, "envelope": assessment,
               "transfer": {"result": reason, "at": "load" if reason == "load_refused" else "park",
                            "steps": list(history)},
               "fail": {"stage": "replan", "class": reason},
               "replan_status": status}
        attempt_id = record(self.config, self.calibration, self.source, self.dest,
                            self.attempt, row, self.t_start, self.choices)
        self.tried.setdefault("replan_from", []).append(attempt_id)
        self.t_start = time.time()
        return attempt_id


def from_receipts(directory: Path) -> list[dict]:
    """Attempt rows rebuilt from receipts (every move() result keeps its attempts), without context."""
    rows = []

    def walk(node, receipt):
        if isinstance(node, dict):
            if isinstance(node.get("attempts"), list) and "from" in node:
                for i, tried in enumerate(node["attempts"]):
                    outcome, stage, why = classify(tried)
                    rows.append({"attempt_id": f"{receipt}-{len(rows)}", "from": node["from"], "to": node["to"],
                                 "attempt": i, **tried, "outcome": outcome, "fail_stage": stage, "fail_class": why})
            for value in node.values():
                walk(value, receipt)
        elif isinstance(node, list):
            for value in node:
                walk(value, receipt)

    for path in sorted(Path(directory).glob("*.json")):
        walk(json.loads(path.read_text()), path.stem)
    return rows


KIN = {}


def arm_error_mm(row: dict, command: str = "goto above_pick"):
    """Measured joints against the sent target at that step, both through the planner's FK: how far the arm
    itself stopped from where it was told (2026-10-28: 2-6 mm across, 3-5 mm low on arm S). Model frame:
    the real zero against the URDF is unmeasured. None when the row kept no joints for that step."""
    step = next((s for s in (row.get("transfer") or {}).get("steps", [])
                 if s.get("command") == command and s.get("state") and s.get("target")), None)
    if step is None:
        return None
    import grasp_planner as gp

    kin = KIN.get("kin") or KIN.setdefault("kin", gp.load_kinematics(None)[0])
    seen, sent = (kin.fk([gp.norm_to_rad(v) for v in q[:5]]) for q in (step["state"], step["target"]))
    return [round(1000 * (seen.x - sent.x), 1), round(1000 * (seen.y - sent.y), 1), round(1000 * (seen.z - sent.z), 1)]


def summary(rows: list[dict], bin_mm: float = 10.0) -> dict:
    """Placed / tried by box position (bins of the located arm point), by map, and the failures. Where a
    row kept the jaws' offset from the box (survey) or the arm's own error, each bin lists them: offset
    minus arm error is what the map got wrong there."""
    by_bin, by_map = defaultdict(Counter), defaultdict(Counter)
    errors = defaultdict(lambda: defaultdict(list))
    for row in rows:
        placed = int(row["outcome"] == "placed")
        arm = (row.get("locate") or {}).get("arm_m")
        key = "not seen" if arm is None else \
            f"x{round(1000 * arm[0] / bin_mm) * bin_mm:.0f} y{round(1000 * arm[1] / bin_mm) * bin_mm:.0f} mm"
        by_bin[(row["from"], key)].update(tried=1, placed=placed)
        if (row.get("survey") or {}).get("offset_mm"):
            errors[(row["from"], key)]["jaw_offset_mm"].append(row["survey"]["offset_mm"])
        arm_error = arm_error_mm(row)
        if arm_error is not None:
            errors[(row["from"], key)]["arm_error_mm"].append(arm_error)
        cal = (row.get("context") or {}).get("calibration") or {}
        by_map[f"{cal.get('sha', '?')} coarse={cal.get('coarse')} loo={cal.get('loo_error_mm')}"].update(
            tried=1, placed=placed)
    from cell_envelope import review_candidates

    return {"attempts": len(rows), "placed": sum(r["outcome"] == "placed" for r in rows),
            "operating_tasks": review_candidates(rows),
            "by_position": {f"{s} {k}": {**c, **errors.get((s, k), {})} for (s, k), c in sorted(by_bin.items())},
            "by_map": {k: dict(c) for k, c in by_map.items()},
            "failures": dict(Counter(f"{r['fail_stage']}: {r['fail_class']}" for r in rows if r["fail_stage"]))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["summary"])
    parser.add_argument("attempts", nargs="*", type=Path, help="attempts.jsonl files")
    parser.add_argument("--receipts", type=Path, action="append", default=[], help="a receipts folder")
    parser.add_argument("--bin-mm", type=float, default=10.0)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for path in args.attempts for line in path.read_text().splitlines() if line.strip()]
    for directory in args.receipts:
        rows += from_receipts(directory)
    print(json.dumps(summary(rows, args.bin_mm), indent=1))


if __name__ == "__main__":
    main()
