#!/usr/bin/env python3
"""Sim-optimised carry parameters for the existing IK carry, per stack tier, and the correction from real results.

  MUJOCO_GL=egl python tools/sim/omx_carry_sweep.py run --tiers 1,2,3 --out DIR [--cands 36 --search 8 --heldout 24 --top 6 --workers 8 --dr FILE --choice preset=v24-20261114]
  python tools/sim/omx_carry_sweep.py rank DIR                   # trials.jsonl -> ranked.json, offers.json, summary.md (no MuJoCo)
  python tools/sim/omx_carry_sweep.py offers DIR --merge review-choices.json     # offers.json -> offline review copy
  python tools/sim/omx_carry_sweep.py ingest DIR --attempts attempts.jsonl [--stack-check TIERPROOF] [--episodes DIR.. --cell FILE]

Only knobs that exist both in the teacher and in the real carry are swept (candidate key -> real setting):
  auto.grasp_depth_m (grasp below the box top; cell_auto_pick_plan), site.place_dz_m (release height over the seat; plan_pick place z),
  auto.jaw_margin_mm (jaw opening beyond the box per side; cell_pick_geom.jaw_open_for). The wrist floor, current caps and TCP are never
  candidates: roll_floor stays at the guard's -18, and the TCP gap (.074 vs .0885) is domain randomisation, not a choice (DR: tcp band, sag_mm residual, zero_deg, physics, vision; arm_b wrist_flex capped at 55.3 in planning).
A run is a trial of one candidate in one scenario = (physics candidate, planner/physical TCP mismatch, joint-zero error ~ FK 8 mm, belt skew,
optionally top-camera jitter + vision pick). Every candidate meets the same scenarios (common random numbers). Success = the teacher's whole-task
judgement (completed: every step pass and every final pose ok) with the held container tilt under SLIP_DEG (the real slip starts near 30 deg);
never a trajectory fit (omx-real-sim-loop: RMS 0.416 deg and 0/9 grasps). MuJoCo answers geometry only (D-947): a sim win is a candidate for
a supervised trial, not real evidence. `ingest` joins real attempts back by candidate id and reweights the scenarios (importance weights
p_real(outcome)/p_sim(outcome)); real failures sim never makes are listed as missing mechanisms, not tuned away.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "deploy/robot/omx")]

SLIP_DEG = 30.0
SIM_MARGIN_MM = 4.0  # per side: the teacher's temp gap .038 for a 30 mm box
GAP_RANGE = (0.032, 0.0435)  # the sim jaw stroke tops out at .0439 (palletizing_gripper.gap_m): real margin 8 mm cannot open further here, so it clamps
BOUNDS = {"auto.grasp_depth_m": (0.008, 0.024), "site.place_dz_m": (0.0, 0.010), "auto.jaw_margin_mm": (2.0, 6.5)}  # real limits are wider (cell_params)
BASELINES = {"sim-default": {"auto.grasp_depth_m": 0.01299, "site.place_dz_m": 0.005, "auto.jaw_margin_mm": 4.0},
             "real-default": {"auto.grasp_depth_m": 0.015, "site.place_dz_m": 0.0, "auto.jaw_margin_mm": 8.0}}
PHYSICS = ("design", "twin-kp-20261109", "servo-friction-20261109", "servo-friction-hold34-20261109", "servo-antijitter-20261112")
# sim_tcp_x_m is what the planner believes (tcp_m + sag); the physical jaw is .0741. Above .0741 the arm undershoots, below it overshoots.
# tcp_m: the jaw TCP is settled (v2.1: CAD .0741, repo STL .0741, touch .0740; the .0885 touch was a wrong table-height assumption, memory arm-b-v21-jaw-tcp), so only
#   its measurement band is drawn: .0740 +-0.8 mm (the STL tip is 74.1 mm and at most 74.8 at any jaw angle; print/assembly tolerance of the same order).
# sag_mm: the remaining joint-zero/sag residual, a SEPARATE term. Measured 2026-11-08: the real table sits 8.3 mm (+-2) under FK 0 (mods.json field_calibration; free descent to
#   FK -6.4 without contact), pose dependent (points 5 mm apart read 5-7.5 mm different). Sign known (the tip stops above the plan: planner TCP too long), so 4..12 mm in 2 mm
#   steps (8.3 +-2 measurement +-2 pose spread); steps keep the cached MuJoCo worlds reusable. Overlaps the zero_deg term a little (+-2 deg is ~8 mm FK): conservative.
# arm_b's wrist_flex is capped at WRIST_FLEX_MAX_NORM in planning (omx-tier-proof joint_max; the printed holder hits link3/4 above it): a plan needing more is a plan failure.
DR = {"tcp_m": [0.0732, 0.0740, 0.0748], "sag_mm": [4.0, 6.0, 8.0, 10.0, 12.0], "zero_deg": [0.0, 2.0], "physics": {p: 1.0 for p in PHYSICS}, "vision_frac": 0.34}
WRIST_FLEX_MAX_NORM = 55.3  # arm_b only, wrist_flex.pos norm unit; joint4
REG = "carry.tier{}"
REAL_KEY = {"site.place_dz_m": "place_dz"}  # the plan's destination-site key (cell_auto_pick_plan); the same mapping as cell_carry_choices.SWEEP_TO_REAL


def wilson(k: int, n: int, z: float = 1.96):
    if not n:
        return [0.0, 1.0]
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def sample_candidates(n: int, seed: int = 0) -> dict:
    """The two baselines plus n-2 stratified random points inside BOUNDS (one stratum per candidate and axis, shuffled)."""
    import random
    rng, out = random.Random(seed), dict(BASELINES)
    cols = {}
    for k, (lo, hi) in BOUNDS.items():
        strata = [(i + rng.random()) / (n - 2) for i in range(n - 2)]
        rng.shuffle(strata)
        cols[k] = [lo + s * (hi - lo) for s in strata]
    for i in range(n - 2):
        out[f"c{i:02d}"] = {k: round(cols[k][i], 5) for k in BOUNDS}
    return out


def draw_scenarios(n: int, seed: int, dr: dict, first_id: int = 0) -> list:
    import random
    rng = random.Random(seed)
    names, w = list(dr["physics"]), list(dr["physics"].values())
    lo, hi = dr["zero_deg"]
    return [dict(id=first_id + i, seed=1000 + seed * 1000 + i, physics=rng.choices(names, w)[0], tcp_m=rng.choice(dr["tcp_m"]),
                 zero_deg=round(rng.uniform(lo, hi), 2), vision=rng.random() < dr["vision_frac"],
                 sag_mm=rng.choice(dr["sag_mm"]) if dr.get("sag_mm") else 0.0) for i in range(n)]


# -- one trial (needs MuJoCo) ----------------------------------------------------------------------------------------------------
_W = {}


def _patch_candidate(params: dict):
    """The candidate's three values into the teacher in this process (no shared sim file is edited: shortcut, upgrade to a Layout choice when the sim files settle)."""
    import omx_two_arm_sites as sites
    import omx_two_arm_teacher_stages as st
    if "base" not in _W:
        _W["base"] = dict(st.OPEN_GAP)
    sites.Layout.hold_below = property(lambda self: self.box[2] / 2 - _W["depth"])
    _W["depth"] = params["auto.grasp_depth_m"]
    for k, v in _W["base"].items():
        st.OPEN_GAP[k] = min(max(v + 2 * (params["auto.jaw_margin_mm"] - SIM_MARGIN_MM) / 1000, GAP_RANGE[0]), GAP_RANGE[1])


def _world(sc: dict):
    key = (sc["physics"], sc["tcp_m"], sc.get("sag_mm", 0.0), sc["vision"], json.dumps(sc.get("extra", {}), sort_keys=True))
    if _W.get("key") != key:
        import omx_two_arm_kin as kin
        import omx_two_arm_sites as sites
        import omx_two_arm_world as wm
        from omx_two_arm_teacher_stages import VISION_SKEW_CHOICES
        extra = dict(sc.get("extra", {}))
        ch = dict(physics=sc["physics"], sim_tcp_x_m=round(sc["tcp_m"] + sc.get("sag_mm", 0.0) / 1000, 5), **extra)
        if sc["vision"]:  # the vision defaults fill what neither the choices nor the scene preset name
            preset = sites.PRESETS.get(extra.get("preset"), {})
            ch = {**{k: v for k, v in VISION_SKEW_CHOICES.items() if k not in preset and k not in extra}, **ch}
        world = wm.World(sites.Layout(**ch))
        cap = float(kin.norm_to_rad(WRIST_FLEX_MAX_NORM))
        for table in (world.layout.arms, world.layout.sim_arms):  # arm_b's planner may not command wrist_flex past the cap
            table["arm_b"].limits[3, 1] = min(table["arm_b"].limits[3, 1], cap)
        _W.update(key=key, world=world)
    return _W["world"]


def classify_run(res: dict, slip_deg: float):
    """(ok, failure class "<phase>:<what>") of one judged run."""
    tilt = max((r.get("held_tilt_max_deg") or 0.0 for r in res["rows"]), default=0.0)
    if res["completed"] and tilt < slip_deg:
        return True, None, tilt
    for r in res["rows"]:
        if r["result"] in ("blocked", "unreachable"):
            return False, f"plan:{r['result']}", tilt
        if r["result"] == "fail":
            phase = next(iter((r.get("first_contact_phase") or {}).values()), "place").split("@")[0] or "place"
            if r.get("arm_arm_contacts") or r.get("arm_link_contacts"):
                return False, f"{phase}:collision", tilt
            if r.get("neighbours_disturbed"):
                return False, f"{phase}:neighbour", tilt
            return False, "place:pose", tilt
    return False, "carry:tilt_slip", tilt


def trial(tier: int, cand: str, params: dict, sc: dict, slip_deg: float = SLIP_DEG) -> dict:
    row = dict(tier=tier, cand=cand, scen=sc["id"], physics=sc["physics"], tcp_m=sc["tcp_m"], sag_mm=sc.get("sag_mm", 0.0), zero_deg=sc["zero_deg"], vision=sc["vision"], seed=sc["seed"])
    t0 = time.time()
    try:
        import omx_two_arm_skill as skill
        import omx_two_arm_tasks as tasks
        import omx_two_arm_teacher as tt
        _patch_candidate(params)
        world = _world(sc)
        task = tasks.get_task(world.layout, f"stack-t{tier}")
        try:
            tasks.validate(world.layout, task)
        except tasks.PlanRefused as e:
            return dict(row, ok=False, cls="plan:refused", detail=str(e)[:160], sec=round(time.time() - t0, 1))
        drop = params["site.place_dz_m"]
        te = tt.Teacher(world, seed=sc["seed"], drop=drop, drop_upper=drop, pick_vision=sc["vision"], belt_skew=True, cam_jitter=sc["vision"])
        if sc["zero_deg"] > 0:
            te.zero_error, te.privileged, te.compensate_zero = skill.draw_zero_error(sc["seed"], sc["zero_deg"]), False, True
        with contextlib.redirect_stdout(io.StringIO()):
            res = te.run_task(task)
        ok, cls, tilt = classify_run(res, slip_deg)
        return dict(row, ok=ok, cls=cls, completed=res["completed"], steps_pass=res["steps_pass"], steps=res["steps"], final_ok=res["final_ok"],
                    final_total=res["final_total"], tilt=round(tilt, 1), sec=round(time.time() - t0, 1))
    except Exception as e:  # a crash is a failure with its own class, never a silent drop
        return dict(row, ok=False, cls="sim_error", detail=f"{type(e).__name__}: {str(e)[:160]}", sec=round(time.time() - t0, 1))


def _unit(job):
    tier, scen, cands = job
    return [trial(tier, c, p, scen) for c, p in cands.items()]


def evaluate(out: Path, tiers, cands: dict, scens: list, workers: int):
    """Run cands x scens for each tier into trials.jsonl; units (tier, scenario) already there are skipped (resume)."""
    path = out / "trials.jsonl"
    done = set()
    if path.exists():
        done = {(r["tier"], r["scen"], r["cand"]) for r in load_trials(out)}
    jobs = []
    for t in tiers:
        for s in sorted(scens, key=lambda s: (s["physics"], s["tcp_m"], s.get("sag_mm", 0.0), s["vision"])):
            todo = {c: p for c, p in cands.items() if (t, s["id"], c) not in done}
            if todo:
                jobs.append((t, s, todo))
    print(f"{len(jobs)} units, {sum(len(j[2]) for j in jobs)} trials", flush=True)
    import multiprocessing as mp
    with path.open("a", encoding="utf-8") as f, mp.get_context("spawn").Pool(workers) as pool:
        for rows in pool.imap_unordered(_unit, jobs, chunksize=1):
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"  tier{rows[0]['tier']} scen{rows[0]['scen']} {sum(r['ok'] for r in rows)}/{len(rows)} {rows[0]['sec']}s/trial", flush=True)


# -- ranking ---------------------------------------------------------------------------------------------------------------------
def load_trials(out: Path) -> list:
    return [json.loads(x) for x in (out / "trials.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def rank(out: Path, search_ids: set, tiers, top: int = 3, slip_deg: float = SLIP_DEG, sha: str = "", preset=None, dr=None, snapshot_sha256=None):
    """Per tier: candidates scored on the held-out scenarios (all non-search ones), tie-break search score, then worst physics."""
    rows = load_trials(out)
    cands = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    result = {}
    for t in tiers:
        by = defaultdict(list)
        for r in rows:
            if r["tier"] == t:
                by[r["cand"]].append(r)
        table = []
        for c, rs in by.items():
            held, srch = [r for r in rs if r["scen"] not in search_ids], [r for r in rs if r["scen"] in search_ids]
            if not held:
                continue
            ph = defaultdict(lambda: [0, 0])
            for r in held:
                ph[r["physics"]][0] += r["ok"]
                ph[r["physics"]][1] += 1
            k, n = sum(r["ok"] for r in held), len(held)
            table.append(dict(cand=c, params=cands[c], k=k, n=n, ci=wilson(k, n), search=[sum(r["ok"] for r in srch), len(srch)],
                              worst_physics=min(a / b for a, b in ph.values()), by_physics={p: v for p, v in sorted(ph.items())},
                              failures=dict(Counter(r["cls"] for r in held if not r["ok"]))))
        table.sort(key=lambda x: (x["ci"][0], x["k"] / max(x["n"], 1), x["worst_physics"], x["search"][0]), reverse=True)
        allr = [r for r in rows if r["tier"] == t and r["scen"] not in search_ids]
        result[t] = dict(top=table[:top], ranked=table, failure_histogram=dict(Counter(r["cls"] for r in allr if not r["ok"])),
                         baselines={b: next((x for x in table if x["cand"] == b), None) for b in BASELINES})
    ids = sorted({r["scen"] for r in rows if r["scen"] not in search_ids})
    meta = dict(sha=sha, slip_deg=slip_deg, heldout_scenarios=len(ids), heldout_seeds=sorted({r["seed"] for r in rows if r["scen"] in ids})[:60],
                at=time.strftime("%Y-%m-%dT%H:%M:%S"), preset=preset, snapshot_sha256=snapshot_sha256,
                dr_digest=hashlib.sha256(json.dumps(dr, sort_keys=True).encode()).hexdigest()[:12] if dr else None)
    (out / "ranked.json").write_text(json.dumps(dict(meta=meta, tiers=result), indent=1), encoding="utf-8")
    write_offers(out, result, meta)
    lines = ["# carry sweep", "", f"sha `{sha[:10]}`, held-out scenarios {len(ids)}, slip limit {slip_deg} deg", "", "| tier | best | held-out k/n | 95% CI | baselines k/n | failures |", "|---|---|---|---|---|---|"]
    for t, d in result.items():
        b = d["top"][0] if d["top"] else None
        bl = ", ".join(f"{n} {v['k']}/{v['n']}" for n, v in d["baselines"].items() if v)
        lines.append(f"| {t} | {b['cand'] if b else '-'} | {f'{b['k']}/{b['n']}' if b else '-'} | {b['ci'] if b else '-'} | {bl} | {d['failure_histogram']} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def write_offers(out: Path, result: dict, meta: dict):
    """The top candidates per tier as a real rosy.omx-cell-choices.v1 file (Choices.offer, source sim), with the sim evidence on each entry."""
    import cell_choices
    p = out / "offers.json"
    p.unlink(missing_ok=True)
    ch = cell_choices.Choices(p)
    for t, d in result.items():
        for x in d["top"]:
            value = dict(candidate=x["cand"], tier=t, **x["params"])
            ch.offer(REG.format(t), value, f"sim:omx_carry_sweep@{meta['sha'][:10]}")
            c = ch._find(REG.format(t), value)
            c["evidence"] = dict(sim_k=x["k"], sim_n=x["n"], ci=x["ci"], seeds=meta["heldout_seeds"], failures=x["failures"], geometry_only="D-947", preset=meta.get("preset"), dr_digest=meta.get("dr_digest"))
    ch.data.update(preset=meta.get("preset"), dr_digest=meta.get("dr_digest"),
                   snapshot_sha256=meta.get("snapshot_sha256"))
    ch.save()


def merge_offers(out: Path, store: Path, preset=None, snapshot_sha256=None) -> dict:
    """offers.json -> an offline choices copy (rosy.omx-cell-choices.v1), values under the real key names. Idempotent: a candidate
    already there is kept as is (its outcomes are never touched); the sim evidence is refreshed only while it has no real try."""
    import cell_choices
    from omx_loop import PRESET, is_live_store

    if is_live_store(store):
        raise ValueError("live site choices cannot be merged by the sweep; use a local review copy")
    src, ch = cell_choices.Choices(out / "offers.json"), cell_choices.Choices(store)
    if snapshot_sha256 is not None and src.data.get("snapshot_sha256") != snapshot_sha256:
        raise ValueError("offers do not match the measured snapshot; rerun the sweep for this snapshot")
    if preset is None:
        preset = PRESET
    entries_all = [(n, e) for n, es in src.data["values"].items() if n.startswith("carry.tier") for e in es]
    bad = sorted({(e.get("evidence") or {}).get("preset") for _, e in entries_all} - {preset}, key=str)
    if bad:  # a sim ranking is only evidence for the layout it was ranked on; refuse before writing anything
        raise ValueError(f"offers ranked on preset {bad} (None = not recorded), but the layout in force is {preset!r}: re-run the sweep with --choice preset={preset}")
    added = kept = 0
    for name, entries in src.data["values"].items():
        for e in entries if name.startswith("carry.tier") else []:
            value = {REAL_KEY.get(k, k): v for k, v in e["value"].items()}
            before = ch._find(name, value)
            ch.offer(name, value, e["source"])
            c = ch._find(name, value)
            if before is None:
                added += 1
            else:
                kept += 1
            if c["tries"] == 0 and "evidence" in e:
                c["evidence"] = e["evidence"]
                if snapshot_sha256 is not None:
                    c["evidence"]["snapshot_sha256"] = snapshot_sha256
    ch.save()
    return dict(added=added, kept=kept, store=str(store))


# -- the correction from reality -------------------------------------------------------------------------------------------------
from omx_carry_sweep_ingest import (  # noqa: E402,F401  (re-exported: existing callers & tests unchanged)
    _tier_of,
    ingest,
    load_verdicts,
    phase_of,
    real_rows,
    real_table,
    tally_real_rows,
    tier_verdict,
    verified_episode_rows,
)


# -- cli -------------------------------------------------------------------------------------------------------------------------
def measured_choices(snapshot, choices):
    import omx_map_gate
    import omx_two_arm_sites as sites
    from omx_real2sim import SCHEMA, SNAP_CHOICES
    from omx_real2sim_refit import GATE_MM

    path = Path(snapshot).resolve()
    value = sites.load_snapshot(path)
    if value.get("schema") != SCHEMA or not value.get("frame"):
        raise SystemExit("sweep requires a cell snapshot with an identified measurement frame")
    if value.get("preset") != choices.get("preset"):
        raise SystemExit("measurement and sweep must use the same preset")
    pads = (value.get("items", {}).get("temp_plates", {}).get("camera_check") or {}).get("worst_mm")
    if not pads or any(type(mm) not in (int, float) or not 0 <= mm <= GATE_MM for mm in pads):
        raise SystemExit("sweep requires an accepted camera pad check")
    choice = dict(choices, **sites.parse_choices(SNAP_CHOICES(path)[1::2]))
    try:
        verdict = omx_map_gate.gate(sites.Layout(**choice))
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"measurement is incomplete: {error}") from error
    if verdict["verdict"] == "refuse":
        raise SystemExit("measurement map refused: " + ", ".join(verdict["why"]))
    return choice


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    specs = {
        "run": [("--tiers", {"default": "1,2,3"}), ("--out", {"required": True}), ("--cands", {"type": int, "default": 36}), ("--top", {"type": int, "default": 6}),
                ("--workers", {"type": int, "default": 8}), ("--seed", {"type": int, "default": 0}), ("--dr", {"help": "a dr_next.json from ingest"}),
                ("--search", {"type": int, "default": 8, "help": "scenarios every candidate runs first"}), ("--heldout", {"type": int, "default": 24, "help": "fresh scenarios for the top candidates"}),
                ("--keep", {"default": "", "help": "comma list of candidate ids that always meet the held-out scenarios (seeds from an earlier run, e.g. c01,c24,c16)"}),
                ("--choice", {"action": "append", "help": "key=value Layout choice for every scenario, e.g. preset=v24-20261114 (the scene)"})],
        "rank": [("out", {})], "ingest": [("out", {}), ("--attempts", {"required": True}), ("--stack-check", {}), ("--episodes", {"nargs": "*"}), ("--cell", {})],
        "offers": [("out", {}), ("--preset", {"help": "the layout preset in force (default: omx_loop PRESET)"}), ("--merge", {"required": True, "help": "local choices review copy (created when missing)"})],
    }
    for name, opts in specs.items():
        sp = sub.add_parser(name)
        for flag, kw in opts:
            sp.add_argument(flag, **kw)
        if name in ("run", "rank", "offers"):
            sp.add_argument("--snapshot", type=Path, help="bind the sweep to this measured cell snapshot")
        if name == "ingest":
            sp.add_argument("--joined", type=Path, help="require the verified attempt and episode join")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sha = os.environ.get("ROSY_SWEEP_SHA", "")
    snapshot = getattr(a, "snapshot", None)
    snapshot_sha256 = hashlib.sha256(snapshot.read_bytes()).hexdigest() if snapshot else None
    if a.cmd == "offers":
        try:
            print(json.dumps(merge_offers(out, Path(a.merge), a.preset, snapshot_sha256)))
        except ValueError as e:
            raise SystemExit(f"refused: {e}")
        return 0
    if a.cmd == "ingest":
        rep = ingest(out, Path(a.attempts), Path(a.stack_check) if a.stack_check else None, a.episodes, a.cell, joined=a.joined)
        print(json.dumps(rep, indent=1)[:3000])
        return 0
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8")) if (out / "meta.json").exists() else {}
    if a.cmd == "run":
        tiers = [int(x) for x in a.tiers.split(",")]
        dr = json.loads(Path(a.dr).read_text(encoding="utf-8")) if a.dr else DR
        cands = sample_candidates(a.cands, a.seed)
        from omx_two_arm_teacher_stages import parse_choices
        extra = parse_choices(a.choice)
        if snapshot:
            extra = measured_choices(snapshot, extra)
        search = [dict(s, extra=extra) for s in draw_scenarios(a.search, a.seed, dr)]
        held = [dict(s, extra=extra) for s in draw_scenarios(a.heldout, a.seed + 1, dr, first_id=1000)]
        trial_config = dict(seed=a.seed, cands=a.cands, top=a.top, search=a.search, heldout=a.heldout, keep=a.keep)
        requested = dict(tiers=tiers, search_ids=[s["id"] for s in search], dr=dr, sha=sha, choices=extra,
                         snapshot_sha256=snapshot_sha256, trial_config=trial_config)
        if (out / "trials.jsonl").exists() and requested != meta:
            raise SystemExit("existing trials use different inputs; use a new --out directory")
        meta = requested
        (out / "candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")
        (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        evaluate(out, tiers, cands, search, a.workers)
        rows = load_trials(out)
        for t in tiers:  # halving: the top candidates by search score (baselines always stay) meet the held-out scenarios
            sc = Counter()
            for x in rows:
                if x["tier"] == t and x["scen"] in meta["search_ids"]:
                    sc[x["cand"]] += x["ok"]
            keep = {c: cands[c] for c, _ in sc.most_common(a.top)} | dict(BASELINES) | {c: cands[c] for c in a.keep.split(",") if c in cands}
            evaluate(out, [t], keep, held, a.workers)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    if snapshot and meta.get("snapshot_sha256") != snapshot_sha256:
        raise SystemExit("trials do not match the measured snapshot; rerun the sweep for this snapshot")
    res = rank(out, set(meta["search_ids"]), meta["tiers"], sha=meta.get("sha") or sha,
               preset=(meta.get("choices") or {}).get("preset"), dr=meta.get("dr"),
               snapshot_sha256=meta.get("snapshot_sha256"))
    print((out / "summary.md").read_text(encoding="utf-8"))
    return 0 if res else 1


if __name__ == "__main__":
    raise SystemExit(main())
