#!/usr/bin/env python3
"""One box to its destination, going on after a failed attempt: the attempt's result and the top camera name the cause, the
table in cell_diagnose (data, not code) names the next action, and each action is tried once per cause, so a retry always
changes something. Then a person decides.

2026-11-07 (arm_b, ship): the first lift of a held box stopped, the retreat pressed it down and the park refused to close on it.
Now run_auto lets go and rises (cell_unwedge.release_and_rise); here a lift stall or a packed box gets a push (cell_align) and
another pick. Folded before and after each attempt, the two top views show what moved: the pile changing away from the box
and its destination means the plan is stale. A push that changed nothing in the view did nothing, and stops.

  cell_recovery.py --config C --catalog K --roi X0 Y0 X1 Y1 --from S --dest D --commissioning --person-at-switch
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

import cell_failure_context as cfc
from cell_failure_vetoes import (
    FALLBACK_VERBS,
    MAX_CHAIN_DEPTH,
    build_allowed_fallback_menu,
    compute_measured_vetoes,
)
import cell_requests

import cell_align
import cell_auto_pick as auto
import cell_decisions as cd
import cell_diagnose
import cell_objects
import cell_pivot
import cell_place_fit
import cell_site_camera
import cell_why
from cell_calibration import load as load_calibration
from cell_scene_guard import scene_moved

NEAR_PX, ROUNDS = 60, 5  # about 1 mm per px in the 650 mm top view; a long box is 90 mm
# what the trace measured -> what it asks for; a model's text never chooses (D-971)
# cell_why reads too_fast only where the same chunk ran on, as fast, lagging as much (its free-run baseline)
PREFER = {"too_fast": "slow_down", "blocked": "push_clear"}
SLOWER, SLOWEST = 0.7, 0.25  # lift_guard_frac: each slow_down, and its floor
MAX_AI_FALLBACK_PER_TASK = MAX_CHAIN_DEPTH
FALLBACK_PREFER = {"too_fast": "retry_ik_slower", "blocked": "align_push"}


def away_from(blobs: list, points: list, near_px: int = NEAR_PX) -> list:
    """The changed regions ([area, x0, y0, x1, y1]) farther than near_px from all of the points where a change is expected."""
    def near(b, p):
        return math.hypot(max(b[1] - p[0], 0, p[0] - b[3]), max(b[2] - p[1], 0, p[1] - b[4])) <= near_px
    return [b for b in blobs if not any(near(b, p) for p in points)]


def options(cause: str, can: set, choices=None, prefer: str | None = None) -> list:
    """The table's actions possible now, best record first; what cell_why read as the cause goes before the record; a person
    stays last and a cause's list is never added to."""
    actions = [a for a in cell_diagnose.next_actions(cause, can, cell_diagnose.RECOVERY) if a != "ask_person"]
    actions = choices.ranked(f"recovery.{cause}", actions) if choices else actions
    return sorted(actions, key=lambda a: a != prefer) + ["ask_person"]


def learned(choices, cause: str, action: str, ok: bool, note: str) -> None:
    if choices:
        choices.offer(f"recovery.{cause}", action, "table")
        choices.outcome(f"recovery.{cause}", action, ok, note[:200])


def unsolved(choices) -> dict:
    """What the cell could not solve itself: cause -> times a person was asked, and the last raw result. The list to add rules for."""
    return {name.removeprefix("recovery."): {"asked": c["tries"], "last": (c["last"] or {}).get("note")}
            for name, values in choices.data["values"].items() if name.startswith("recovery.")
            for c in values if c["value"] == "ask_person" and c["tries"]}


def moving_rects(config: dict) -> list:
    """The belt's top-view rects ([x0, y0, x1, y1]): delegated to `cell_scene_guard.moving_rects`."""
    import cell_scene_guard

    return cell_scene_guard.moving_rects(config)


def at_home(state, home: list, tolerance: float = 2.0) -> bool:
    """The body joints are folded; the jaws do not count. No reading is not home."""
    return bool(state) and max(abs(a - b) for a, b in zip(state[:5], home[:5])) <= tolerance


def carry(frame, pick, push, *, expected_px, emit=cd.emit, rounds: int = ROUNDS, choices=None, explain=None, slow=None, folded=None,
          observe=None, camera=None, ignore=()) -> dict:
    """pick() -> run_auto's result; push(cause, attempt) -> whether it moved the arm; expected_px(attempt) -> pixels of the
    pick and the place; frame() -> the top view with the arm folded. An action earns its record from the next attempt: only a
    placed box counts as working, and `choices` then ranks the actions next time. explain(cause, out) -> cell_why's row: what it
    measured orders the actions, and a cause unknown again goes to a person. slow() -> lowered the lift speed, or at the floor.
    folded() -> the arm came home: a fold can fail after a stop, and no retry starts from there. observe() -> a site camera's
    frame of a failure (cell_site_camera): kept on the row as evidence, never read by the choice of action. camera(frame) ->
    the top camera's shift when it moved off the map's reference, else None: checked before every pick, no motion on a stale
    map. ignore: rects that always change (the belt), left out of both scene checks."""
    tried, rows, pending = {}, [], None
    try:
        for _ in range(rounds):
            before = frame()
            shift = camera(before) if camera else None
            if shift:
                rows.append({"result": "camera moved", "cause": "camera_moved", "camera_shift": shift, "action": "ask_person"})
                emit("recovery", rows[-1], cell_diagnose.RECOVERY["camera_moved"], "ask_person", "rule", "camera moved")
                return {"result": "ask a person: camera_moved", "rounds": rows, "ask": cell_diagnose.ASK["camera_moved"]}
            out = pick()
            attempt = (out.get("attempts") or [{}])[-1]
            moved = away_from(scene_moved(before, frame(), ignore), expected_px(attempt))
            cause = cell_diagnose.attempt_cause(out["result"], bool(moved))
            if pending:
                learned(choices, *pending, cause == "placed", out["result"])
                pending = None
            why = explain(cause, out) if explain and cause != "placed" else {}
            can = ({"observe_again", "push_clear"} | ({"slow_down"} if slow else set())) - set(tried.setdefault(cause, []))
            action = "done" if cause == "placed" else options(cause, can, choices, PREFER.get(why.get("hypothesis")) if why.get("by") == "measurement" else None)[0]
            if why.get("repeat_unknown") or (folded and action != "done" and not folded()):
                action = "ask_person"
            if action == "slow_down" and not slow():
                learned(choices, cause, action, False, "the lift is at its slowest")
                action = "ask_person"
            if action == "push_clear":
                before = frame()
                if not push(cause, attempt) or not scene_moved(before, frame(), ignore):
                    learned(choices, cause, action, False, "the push changed nothing in the top view")
                    action = "ask_person"
            if action == "ask_person":
                learned(choices, cause, action, False, out["result"])
            rows.append({"result": out["result"], "cause": cause, "pile_moved": moved, "action": action,
                         "why": why.get("hypothesis"), "missing": why.get("missing", []),
                         **({"evidence": observe()} if observe and cause != "placed" else {})})
            emit("recovery", rows[-1], cell_diagnose.RECOVERY.get(cause, []), action, "rule", f"cause {cause}")
            if action in ("done", "ask_person"):
                return {"result": "placed" if action == "done" else f"ask a person: {cause}", "rounds": rows,
                        **({"ask": cell_diagnose.ASK[cause]} if action == "ask_person" and cause in cell_diagnose.ASK else {})}
            tried[cause].append(action)
            pending = (cause, action)
        return {"result": f"ask a person: {rounds} rounds", "rounds": rows}
    finally:
        if choices:
            choices.save()


def main(argv=None) -> int:
    import cell_choices
    from cell_auto_setup import open_cell, parser

    ap = parser(__doc__)
    ap.add_argument("--commissioning", action="store_true", help="a supervised trial (D-911)")
    ap.add_argument("--person-at-switch", action="store_true", help="with --commissioning: a person is at the power switch")
    args = ap.parse_args(argv)
    if args.dry_run:
        ap.error("recovery has no dry run: use cell_auto_pick --dry-run for the plan, cell_failure_scenarios for the decisions")
    if not (args.commissioning and args.person_at_switch):
        ap.error("recovery moves the arm outside the D-911 gate: --commissioning --person-at-switch")
    args.push_site = args.source
    config, cell, calibration_path, work = open_cell(args, True)
    catalog = cell_objects.load_catalog(args.catalog)
    calibration = cell_pivot.with_site_maps(config, load_calibration(calibration_path))
    # `pallet-l1` style destinations exist only after the tier expansion (2026-11-17 ValueError). Only names and
    # pixels use the tiered copy: the map binding digests the calibration's sites, so a tiered calibration read as
    # "top camera calibration changed" and refused every live carry (2026-11-17); run_auto expands tiers itself.
    tiered, tiered_cal = cell_place_fit.with_tiers(config, calibration, catalog)
    site_of = {"pick": args.source, "place": auto.parse_dest(tiered, args.source, args.dest)[0]}

    def expected_px(attempt):
        plan = attempt.get("plan") or {}
        points = [auto.predicted_pixel(tiered, tiered_cal, site_of[k], (plan[k]["x"], plan[k]["y"])) for k in plan if k in site_of]
        return [p for p in points if p is not None]

    choices = cell_choices.Choices(work / "choices.json")  # one copy: run_auto's closing-axis records and these share the file

    def pick():
        return auto.run_auto(cell, config, calibration, calibration_path, catalog, args.roi, args.source, args.dest, work, choices)

    def push(cause, attempt):
        packed = None
        if cause == "lift_stall":  # it looks free: the box under the stalled lift is the one to move
            _, _, objects, error = auto.observe(cell, config, calibration, args.source, args.roi, catalog)
            pick_at = (attempt.get("plan") or {}).get("pick")
            if error or not objects or not pick_at:
                return False
            packed = [min(objects, key=lambda o: math.dist(o["raw_m"], (pick_at["x"], pick_at["y"])))["centre_mm"]]
        step = cell_align.next_step(cell, config, calibration, calibration_path, catalog, args.roi, args.source, args.push_site,
                                    args.dest, work, packed)
        print(json.dumps({"next": step}, default=str), flush=True)
        return step["step"] in ("push", "pivot") and cell_align.run_step(step, args) == 0

    why_path, started = work / "why.jsonl", time.time()

    def explain(cause, out):  # measurement only: the control PC does not call a model; Fleet hands the incident to the AI PC (D-971)
        # shortcut: the newest trace in the working folder, as the session script writes it; upgrade if a run ever starts elsewhere
        traces = sorted(Path(".").glob(f"trace-{config.get('arm_id', 'arm_s')}-*.jsonl"), key=lambda p: p.stat().st_mtime)
        rows = cell_why.read_trace(traces[-1]) if traces else []
        # the carry's finished runs join the baseline before the stop is read against it
        return cell_why.explain(cause, out["result"], rows, [], None, why_path, since=started, free=cell_why.learn(rows, work / "free_lag.json"))

    def slow():
        slower = round(config["plan"].get("lift_guard_frac", 0.85) * SLOWER, 3)
        if slower < SLOWEST:
            return False
        config["plan"]["lift_guard_frac"] = slower
        return True

    import cell_calibrate

    if not (config.get("preflight") or {}).get("reference_top"):
        ap.error("no preflight.reference_top: recovery cannot tell a moved top camera, so it does not move the arm")

    def moved_camera(frame):
        found = cell_calibrate.check(config, calibration, [], frame, config.get("params"))
        if found.get("no_reference"):
            return {"why": "the reference frame is missing"}
        return found["camera_shift"] if found["camera_moved"] else None

    evidence = config.get("evidence_camera")
    observe = (lambda: cell_site_camera.fleet_frame(evidence, work / "evidence")) if evidence else None
    out = carry(lambda: cell.frame("top"), pick, push, expected_px=expected_px, choices=choices, explain=explain, slow=slow,
                folded=lambda: at_home(cell.act("state").get("state"), config["plan"]["home"]), observe=observe,
                camera=moved_camera, ignore=moving_rects(config))
    print(json.dumps({**out, "unsolved": unsolved(choices), "open_questions": cell_why.open_questions(why_path)}, indent=1, default=str))
    return 0 if out["result"] == "placed" else 1


def _escalate_selection(reason: str) -> dict:
    return {
        "verb": "escalate_human",
        "tier": 0,
        "stratum": "human_only",
        "target_surface": "human_request",
        "requires_human_operator": True,
        "requires_person_at_switch": False,
        "escalate": True,
        "reason": reason,
    }


def _verified_menu(bundle: dict, fallback_chain_depth: int) -> tuple[list[dict], str | None]:
    if not isinstance(bundle, dict):
        return [], "missing failure bundle"
    if isinstance(fallback_chain_depth, bool) or not isinstance(fallback_chain_depth, int) or fallback_chain_depth < 0:
        return [], f"invalid fallback_chain_depth {fallback_chain_depth!r}"
    if fallback_chain_depth >= MAX_AI_FALLBACK_PER_TASK:
        return [], f"fallback chain depth {fallback_chain_depth} >= {MAX_AI_FALLBACK_PER_TASK}"
    exp_sha = bundle.get("context_sha256")
    if not isinstance(exp_sha, str) or exp_sha != cfc.canonical_sha256(bundle):
        return [], "bundle context_sha256 missing or tampered"
    history = bundle.get("history_and_constraints") or {}
    if history.get("repeat_unknown_tripped"):
        return [], "repeat_unknown tripped: escalating to human"
    meas = bundle.get("measurement") or {}
    spatial = bundle.get("spatial") or {}
    visual = bundle.get("visual") or {}
    cause = str((meas.get("outcome") or {}).get("attempt_cause") or "other")
    exec_mode = str(bundle.get("executor_mode") or (bundle.get("executor") or {}).get("mode") or "")
    orig_menu = history.get("allowed_fallback_menu") or ()
    has_redir = any(isinstance(m, dict) and m.get("verb") == "redirect_alt_dest" for m in orig_menu)
    auto_fold = any(isinstance(m, dict) and m.get("verb") == "home_unwedge" and m.get("tier") == 2 for m in orig_menu)
    pending = bool(history.get("pending_intent_present") or any(
        isinstance(v, dict) and v.get("code") == "PENDING_INTENT_PRESENT" for v in (history.get("measured_vetoes") or ())
    ))
    vetoes = compute_measured_vetoes(meas, spatial, visual, pending_intent_present=pending, repeat_unknown_tripped=False)
    menu = build_allowed_fallback_menu(
        exec_mode, cause, vetoes, fallback_chain_depth=fallback_chain_depth,
        has_declared_alternates=has_redir, dest_full_pre_motion=has_redir, auto_fold_armed=auto_fold,
    )
    return [item for item in menu if isinstance(item, dict) and item.get("verb") in FALLBACK_VERBS], None


def permitted_fallback_verbs(bundle: dict, *, fallback_chain_depth: int = 0) -> list[str]:
    """Return permitted fallback verbs recomputed from verified bundle measurements."""
    menu, err = _verified_menu(bundle, fallback_chain_depth)
    if err:
        return ["escalate_human"]
    return [m["verb"] for m in menu if m.get("preconditions_met") is True and not m.get("blocked_by")] or ["escalate_human"]


def select_fallback(
    bundle: dict,
    *,
    proposed_verb: str | None = None,
    fallback_chain_depth: int = 0,
    choices=None,
    why_row: dict | None = None,
) -> dict:
    """Pure selection over closed `FALLBACK_VERBS` & bundle vetoes; enforces depth<=2 and Tier-1 policy->IK gate."""
    menu, err = _verified_menu(bundle, fallback_chain_depth)
    if err:
        return _escalate_selection(err)
    permitted = {
        item["verb"]: item
        for item in menu
        if item.get("preconditions_met") is True and not item.get("blocked_by")
    }
    if proposed_verb is not None:
        if proposed_verb not in FALLBACK_VERBS:
            return _escalate_selection(f"unknown fallback verb {proposed_verb!r}")
        item = permitted.get(proposed_verb)
        if item is None:
            return _escalate_selection(f"verb {proposed_verb!r} blocked or absent in allowed_fallback_menu")
        if item.get("tier") == 1 and item.get("requires_human_operator") is not True:
            return _escalate_selection(f"Tier-1 verb {proposed_verb!r} requires human operator approval")
        if proposed_verb == "escalate_human":
            return _escalate_selection("selected escalate_human")
        return {
            "verb": proposed_verb,
            "tier": int(item.get("tier", 1)),
            "stratum": str(item.get("stratum") or "tier1_propose"),
            "target_surface": str(item.get("target_surface") or "cell_job_api"),
            "requires_human_operator": bool(item.get("requires_human_operator", True)),
            "requires_person_at_switch": bool(item.get("requires_person_at_switch", True)),
            "escalate": bool(item.get("requires_human_operator", True)),
            "reason": f"permitted {proposed_verb}",
            "menu_item": item,
        }

    outcome = (bundle.get("measurement") or {}).get("outcome") or {}
    cause = str(outcome.get("attempt_cause") or "other")
    exec_mode = str(bundle.get("executor_mode") or (bundle.get("executor") or {}).get("mode") or "")
    if exec_mode in ("act_paced", "act_timed", "hybrid") or exec_mode.startswith(("act", "policy", "smolvla")):
        if "propose_ik_fallback_for_policy" in permitted:
            return select_fallback(bundle, proposed_verb="propose_ik_fallback_for_policy", fallback_chain_depth=fallback_chain_depth)
    non_esc = [v for v in permitted if v != "escalate_human"]
    if not non_esc:
        return _escalate_selection(f"no permitted automated/proposed verb for {cause}")
    ranked = choices.ranked(f"fallback.{cause}", non_esc) if choices else non_esc
    prefer = FALLBACK_PREFER.get((why_row or {}).get("hypothesis")) if (why_row or {}).get("by") == "measurement" else None
    if prefer in ranked:
        chosen = prefer
    else:
        chosen = ranked[0]
    return select_fallback(bundle, proposed_verb=chosen, fallback_chain_depth=fallback_chain_depth)


def escalate_to_request(
    bundle: dict,
    *,
    selection: dict | None = None,
    reason: str = "",
    image: Path | None = None,
    root: Path | None = None,
) -> dict:
    """Persist an actionable `cell_requests` check item from a `CellFailureContext` bundle."""
    bid = str(bundle.get("bundle_id") or "cell-failure")
    req_id = re.sub(r"[^A-Za-z0-9_-]", "-", f"esc-{bid}")[:64].strip("-") or "esc-cell-failure"
    arm_id = str(bundle.get("arm_id") or "arm_s")
    outcome = (bundle.get("measurement") or {}).get("outcome") or {}
    cause = str(outcome.get("attempt_cause") or "other")
    hist = bundle.get("history_and_constraints") or {}
    raw_vetoes = hist.get("measured_vetoes") or ()
    vetoes = [v.get("code") for v in raw_vetoes if isinstance(v, dict) and v.get("code")]
    sel_verb = (selection or {}).get("verb") or "escalate_human"
    why_text = reason or (selection or {}).get("reason") or cell_diagnose.ASK.get(cause) or str(outcome.get("result_text") or cause)
    req = {
        "id": req_id,
        "kind": "check",
        "item": f"{arm_id}-{cause}",
        "question": f"Approve or resolve {arm_id} failure ({cause}; verb={sel_verb})? [{why_text[:120]}]",
        "how": f"Inspect failure bundle {bid} and physical workspace on {arm_id}, then answer pass/fail.",
        "steps": [
            f"Inspect {arm_id} physical state and clear any incident/hold",
            f"Review bundle {bid} vetoes={vetoes} proposed={sel_verb}",
            f"Confirm resolution or next operator action for {cause}",
        ],
        "why": why_text[:200],
        "arm_id": arm_id,
        "bundle_id": bid,
        "attempt_cause": cause,
        "context_sha256": bundle.get("context_sha256"),
        "selected_verb": sel_verb,
        "vetoes": vetoes,
    }
    rdir = Path(root) if root is not None else cell_requests.store()
    existing = rdir / f"{req_id}.json"
    if existing.is_file():
        loaded = json.loads(existing.read_text(encoding="utf-8"))
        if loaded.get("bundle_id") == bid and loaded.get("context_sha256") == bundle.get("context_sha256") and loaded.get("status") == "open":
            return loaded
        for i in range(1, 100):
            cand = f"{req_id[:58]}-{i}"
            if not (rdir / f"{cand}.json").exists():
                req["id"] = cand
                break
    return cell_requests.open_request(req, image=image, root=root)


if __name__ == "__main__":
    sys.exit(main())
