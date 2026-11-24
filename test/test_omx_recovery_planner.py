"""Unit tests for multi-site corridor checks, tier-1 per-arm recovery planning, tier-2 AI-PC advisor, and unwedge FK-z guard."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_fold as af  # noqa: E402
import cell_corridor as cc  # noqa: E402
import cell_recovery_advisor as cra  # noqa: E402
import cell_recovery_plan as crp  # noqa: E402
import cell_unwedge as cu  # noqa: E402

ROI = (0, 0, 400, 400)
HOME_B = [0.8, -62.2, 53.0, 51.9, 44.6, 48.8]


def _to_px(p):
    return (200.0 + p[0] * 1000.0, 200.0 + p[1] * 1000.0)


def test_corridor_multi_site_high_surface_clears_gap_and_keeps_low_and_obstacle_safety():
    site_a = [[240, 260], [340, 260], [340, 340], [240, 340]]  # y in +60..+140 mm
    site_b = [[240, 60], [340, 60], [340, 140], [240, 140]]    # y in -140..-60 mm
    hull = cc.transit_hull_polygon([site_a, site_b])
    # Leg starts low in site_b, transits high at 138 mm across gap y=-60..+60, descends low in site_a
    tcp = (
        [(0.09, -0.10, 0.04)] * 3
        + [(0.11, y, 0.14) for y in np.linspace(-0.08, 0.08, 20)]
        + [(0.09, 0.10, 0.04)] * 3
    )
    empty = np.zeros((400, 400), np.uint8)
    # Single surface_px blocks due to off_surface across gap/other site
    blocked_single = cc.check(tcp, empty, ROI, _to_px, surface_px=site_b)
    assert not blocked_single["clear"] and blocked_single["off_surface"] > 0
    # Combined low surfaces + convex hull high_surface_px clears empty gap
    cleared = cc.check(tcp, empty, ROI, _to_px, surface_px=[site_a, site_b], high_surface_px=hull)
    assert cleared["clear"] and cleared["off_surface"] == 0
    # Unknown blob in the inter-site high transit gap STILL blocks
    obs = empty.copy()
    gx, gy = _to_px((0.11, 0.0))
    obs[int(gy) - 10:int(gy) + 10, int(gx) - 10:int(gx) + 10] = 1
    hit_gap = cc.check(tcp, obs, ROI, _to_px, surface_px=[site_a, site_b], high_surface_px=hull)
    assert not hit_gap["clear"] and hit_gap["high"]
    # Low descent outside calibrated low surface polygons STILL fails off_surface (sliver protection preserved)
    low_outside = [(0.11, 0.0, 0.04)] * 4
    sliver_fail = cc.check(low_outside, empty, ROI, _to_px, surface_px=[site_a, site_b], high_surface_px=hull)
    assert not sliver_fail["clear"] and sliver_fail["off_surface"] > 0


def test_tier1_pan10_chunks_jogs_and_polls_settle_and_respects_arm_a_bounds():
    cmds10 = crp.chunk_jog_commands("shoulder_pan.pos", 10.0)
    assert cmds10 == ["jog shoulder_pan.pos 5.0", "jog shoulder_pan.pos 5.0"]
    assert all(abs(float(c.split()[-1])) <= crp.STEP_MAX for c in crp.chunk_jog_commands("shoulder_pan.pos", -15.0))

    # arm_a limits prune pan/candidates leaving joint_min/joint_max, while keeping elbow_clear_then_park
    cfg_a = {"joint_min": {"wrist_roll.pos": -31.0, "shoulder_pan.pos": -40.0}, "joint_max": {"wrist_flex.pos": 56.0}}
    bounds_a = crp.joint_bounds(cfg_a)
    state_a = [-35.0, -58.0, 50.0, 52.0, 20.0, 48.8]  # rolled near arm_a wrist-cam interference; pan-10 would leave -40
    home_a = [0.0, -58.0, 50.0, 52.0, 45.0, 48.8]
    cands_a = crp.build_candidates(state_a, home_a, 48.8, lambda s: [s, home_a], bounds=bounds_a, extended=True)
    names_a = [c[0] for c in cands_a]
    assert "pan-10" not in names_a and "pan-15" not in names_a
    assert "elbow_clear_then_park" in names_a

    # Slow settling cell fails closed with DETOUR_NOT_SETTLED and keeps torque ON
    class _StuckSettleCell:
        def __init__(self):
            self.cmds = []
            self.state = [0.0, -20.0, 20.0, 45.0, -5.0, 48.8]
            self.target = list(self.state)

        def act(self, cmd: str):
            self.cmds.append(cmd)
            if cmd == "state":
                return {"ok": True, "state": list(self.state), "target": list(self.target), "holding": False}
            if cmd.startswith("jog "):
                self.target[0] += float(cmd.split()[-1])  # simulated motor never catches up (> SETTLE_TOL)
                return {"ok": True, "state": list(self.state), "target": list(self.target)}
            if cmd == "human-hold":
                return {"ok": True, "human_hold_latched": True, "state": list(self.state)}
            raise AssertionError(cmd)

    cell = _StuckSettleCell()
    res = af.recover(
        cell, [0.0, -58.0, 50.0, 50.0, -5.0, 48.8], 48.8,
        plan=lambda s: [s, [0.0, -58.0, 50.0, 50.0, -5.0, 48.8]],
        look=lambda frames: {"clear": any(abs(f[0]) >= 9.0 for f in frames), "low": [], "high": []},
        reserve=lambda _f: {"ok": True}, release=lambda: None,
        release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: False,
        sleep=lambda _s: None,
    )
    assert res["result"] == "held" and res["reason"] == "DETOUR_NOT_SETTLED"
    assert cell.cmds[-1] == "human-hold" and "park" not in cell.cmds


def test_tier1_low_open_jaws_prefers_lift_then_park_over_bare_park_and_checks_load():
    # Pose on arm_b low over belt with open jaws (z < 0.10, gripper=58 > 48.8 + 4)
    from cell_control_core import rad_to_norm
    from grasp_planner import load_kinematics
    from omx_adapter.kinematics import TopDownPose, IkLimits

    kin = load_kinematics(None, 0.0740)[0]
    lim = IkLimits(
        position_limits={k: (-2.6, 2.6) for k in ("joint1", "joint2", "joint3", "joint4", "joint5")},
        workspace_min_m=(-0.4, -0.4, -0.1), workspace_max_m=(0.4, 0.4, 0.5),
        singularity_radius_m=0.02,
    )
    ik = kin.solve_top_down(TopDownPose(0.16, 0.06, 0.02, 0.0), lim)
    assert ik.ok
    state_low = [rad_to_norm(v) for v in ik.joints] + [58.0]
    assert crp.fk_z(state_low, tcp_x_m=0.0740) < 0.10

    situation = crp.classify_situation(state_low, state_low, HOME_B, 48.8, low_ok=True, is_holding=False)
    assert situation == "low_open_jaws"
    cands = crp.build_candidates(
        state_low, HOME_B, 48.8, lambda s: [s, HOME_B], tcp_x_m=0.0740,
        clear_z_m=0.10, situation=situation, extended=True,
    )
    assert cands[0][0] == "lift_then_park"
    assert cands[0][1] and all(abs(float(c.split()[-1])) <= crp.STEP_MAX for c in cands[0][1])

    # Load check rejects risky candidate and picks next clear safe candidate
    seen_checks = []

    def fake_load(frames):
        seen_checks.append(len(frames))
        return {"ok": len(seen_checks) > 1, "verdict": "risky" if len(seen_checks) == 1 else "ok"}

    class _MinCell:
        def __init__(self):
            self.cmds = []
            self.s = list(state_low)

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd == "state":
                return {"ok": True, "state": list(self.s), "target": list(self.s), "holding": False}
            if cmd.startswith("jog "):
                _, n, d = cmd.split()
                idx = crp.NAMES.index(n)
                self.s[idx] += float(d)
                return {"ok": True, "state": list(self.s), "target": list(self.s)}
            if cmd == "park":
                self.s = list(HOME_B)
                return {"ok": True, "settled": True, "state": list(HOME_B), "target": list(HOME_B)}
            return {"ok": True, "state": list(self.s)}

    cell = _MinCell()
    out = af.recover(
        cell, HOME_B, 48.8, plan=lambda s: [s, HOME_B],
        look=lambda _f: {"clear": True, "low": [], "high": []},
        reserve=lambda _f: {"ok": True}, release=lambda: None,
        release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: True,
        load_check=fake_load, tcp_x_m=0.0740, clear_z_m=0.10, extended_detours=True, sleep=lambda _s: None,
    )
    assert out["result"] == "folded" and out["candidate"] != "lift_then_park"
    assert any(s.get("step") == "load_check" and s.get("verdict") == "risky" for s in out["steps"])


def test_advisor_schema_vetoes_numeric_translation_and_auto_fold_integration():
    # 1. Strict D-878 schema & hard veto checks
    bad_cases = [
        ("not-dict", False, True, "INVALID_TYPE"),
        ({"strategy": "lift_then_park"}, False, True, "SCHEMA_KEYS_MISMATCH"),
        ({"strategy": "lift_then_park", "lift_mm": True, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": False, "confidence": 0.9, "reason": "x"}, False, True, "SCHEMA_VALUE_OUT_OF_RANGE"),
        ({"strategy": "lift_then_park", "lift_mm": 999.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": False, "confidence": 0.9, "reason": "x"}, False, True, "SCHEMA_VALUE_OUT_OF_RANGE"),
        ({"strategy": "lift_then_park", "lift_mm": 20.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": True, "confidence": 0.9, "reason": "drop"}, True, False, "VETO_HOLDING_HIGH"),
        ({"strategy": "lift_then_park", "lift_mm": 20.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": True, "confidence": 0.9, "reason": "open high"}, False, False, "VETO_OPEN_JAWS_FORBIDDEN"),
        ({"strategy": "lift_then_park", "lift_mm": 20.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": False, "confidence": 0.4, "reason": "unsure"}, False, True, "LOW_CONFIDENCE"),
        ({"strategy": "lift_then_park", "lift_mm": 20.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": True, "confidence": 0.9, "reason": "open low"}, False, True, "OPEN_JAWS_UNSUPPORTED"),
        ({"strategy": "lift_pan_then_park", "lift_mm": 0.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 20.0,
          "open_jaws": False, "confidence": 0.9, "reason": "skip lift"}, False, True, "STRATEGY_PARAM_MISMATCH"),
        ({"strategy": "pan_then_park", "lift_mm": 0.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 20.0,
          "open_jaws": False, "confidence": 0.9, "reason": "pan low"}, False, True, "VETO_PAN_WHILE_LOW"),
        ({"strategy": "escalate_human", "lift_mm": 0.0, "elbow_retract_deg": 0.0, "pan_detour_deg": 0.0,
          "open_jaws": False, "confidence": 0.9, "reason": "hand"}, False, False, "escalate_human"),
    ]
    for raw, holding, low, code in bad_cases:
        clean, veto = cra.validate_proposal(raw, holding=holding, low=low)
        assert clean is None and veto == code

    # 2. Numeric translation with REAL OmxKinematics: lifts z past clear_z_m before panning, chunks <= 5.0
    state_reach = [22.2, 8.8, 5.5, 23.9, -24.6, 54.2]
    z0 = crp.fk_z(state_reach, tcp_x_m=0.0740)
    prop = {
        "strategy": "lift_pan_then_park", "lift_mm": 75.0, "elbow_retract_deg": 0.0,
        "pan_detour_deg": 32.0, "open_jaws": False, "confidence": 0.92, "reason": "clear obstacle then pan",
    }
    clean, veto = cra.validate_proposal(prop, holding=False, low=True)
    assert veto is None
    cand, meta = cra.translate_proposal(clean, state_reach, state_reach, HOME_B, lambda s: [s, HOME_B], tcp_x_m=0.0740)
    assert cand is not None and meta["achieved_lift_mm"] >= 64.0
    name, cmds, frames = cand
    assert name == "advisor:lift_pan_then_park"
    assert all(abs(float(c.split()[-1])) <= crp.STEP_MAX for c in cmds)
    first_pan_idx = next(i for i, f in enumerate(frames) if abs(f[0] - state_reach[0]) > 0.5)
    assert crp.fk_z(frames[first_pan_idx - 1], tcp_x_m=0.0740) >= 0.10
    assert (crp.fk_z(frames[first_pan_idx - 1], tcp_x_m=0.0740) - z0) * 1000.0 >= 64.0
    # Insufficient lift below clear_z_m before pan is vetoed, and origin tracks `target` under lag
    low_lift = {**prop, "lift_mm": 40.0}
    cand_bad, meta_bad = cra.translate_proposal(low_lift, state_reach, state_reach, HOME_B, lambda s: [s, HOME_B], tcp_x_m=0.0740)
    assert cand_bad is None and meta_bad["rejected"] == "PAN_BELOW_CLEAR_Z"
    target_lag = [22.2, 6.8, 5.5, 23.9, -24.6, 54.2]
    cand_lag, _ = cra.translate_proposal(clean, state_reach, target_lag, HOME_B, lambda s: [s, HOME_B], tcp_x_m=0.0740)
    assert cand_lag is not None and cand_lag[2][0] == target_lag
    assert cra._clamp_timeout({"timeout_s": None}, 10.0)["timeout_s"] == 10.0

    # 3. End-to-end auto_fold integration: tier-1 blocked -> advisor proposal verified -> folded, _learn skips advisor:*
    class _VlmCell:
        def __init__(self):
            self.cmds = []
            self.s = list(state_reach)

        def frame(self, _role):
            return np.zeros((16, 16, 3), np.uint8)

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd == "state":
                return {"ok": True, "state": list(self.s), "target": list(self.s), "holding": False}
            if cmd.startswith("jog "):
                _, j, d = cmd.split()
                self.s[crp.NAMES.index(j)] += float(d)
                return {"ok": True, "state": list(self.s), "target": list(self.s)}
            if cmd == "park":
                self.s = list(HOME_B)
                return {"ok": True, "settled": True, "state": list(HOME_B), "target": list(HOME_B)}
            if cmd == "human-hold":
                return {"ok": True, "human_hold_latched": True, "state": list(self.s)}
            raise AssertionError(cmd)

    cell = _VlmCell()
    advisor = cra.make_advisor(
        lambda _p, _imgs, _sch: dict(prop), cell, home=HOME_B,
        plan=lambda s: [s, HOME_B], tcp_x_m=0.0740,
    )
    res = af.recover(
        cell, HOME_B, 48.8, plan=lambda s: [s, HOME_B],
        look=lambda frames: {"clear": abs(frames[max(0, len(frames) - 3)][0] - state_reach[0]) > 16.0, "low": [], "high": []},
        reserve=lambda _f: {"ok": True}, release=lambda: None,
        release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: True,
        advisor=advisor, sleep=lambda _s: None,
    )
    assert res["result"] == "folded" and res["candidate"] == "advisor:lift_pan_then_park"
    assert any(s.get("step") == "advisor" and s.get("ok") is True for s in res["steps"])
    # propose_only=True logs proposal without moving anything
    cell_po = _VlmCell()
    advisor_po = cra.make_advisor(
        lambda _p, _imgs, _sch: dict(prop), cell_po, home=HOME_B,
        plan=lambda s: [s, HOME_B], tcp_x_m=0.0740, propose_only=True,
    )
    res_po = af.recover(
        cell_po, HOME_B, 48.8, plan=lambda s: [s, HOME_B],
        look=lambda _f: {"clear": False, "low": [], "high": []},
        reserve=lambda _f: {"ok": True}, release=lambda: None,
        release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: True,
        advisor=advisor_po, sleep=lambda _s: None,
    )
    assert res_po["result"] == "held" and res_po["reason"] == "ALL_PATHS_BLOCKED"
    assert cell_po.cmds == ["state", "human-hold"]
    assert any(s.get("step") == "advisor" and s.get("propose_only") is True for s in res_po["steps"])
    # _learn ignores advisor:* without KeyError
    af._learn({"choices_path": "nonexistent-choices.json", "candidate": "advisor:lift_pan_then_park"}, True)


def test_unwedge_skips_dipping_pull_when_clear_z_m_is_set():
    class _UnwedgeCell:
        def __init__(self):
            self.cmds = []
            self.s = [22.2, -20.0, 20.0, 45.0, 44.6, 48.8]
            self.t = list(self.s)

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd.startswith("jog "):
                _, j, d = cmd.split()
                idx = cu.BODY.index(j.removesuffix(".pos"))
                self.t[idx] += float(d)
                self.s[idx] = self.t[idx]
            if cmd == "park":
                self.s[:5] = list(cu.HOME)
                self.t[:5] = list(cu.HOME)
                return {"ok": True, "settled": True, "state": list(self.s), "target": list(self.t)}
            return {"ok": True, "state": list(self.s), "target": list(self.t)}

    cell = _UnwedgeCell()
    out = cu.unwedge(cell, cu.HOME, sleep=lambda _s: None, clear_z_m=0.14)
    assert out["result"] == "recovered"
    # On step 3 (where decide() normally switches to 'pull'), pull dips FK-z while < 0.14m so lift continues first
    assert out["rows"][3]["action"] == "lift"


def test_choices_ranking_cannot_bypass_low_open_jaws_lift_priority(tmp_path):
    from cell_choices import Choices

    cp = tmp_path / "choices.json"
    ch = Choices(cp)
    for name in crp.extended_candidate_names():
        ch.offer(af.CHOICE, name, "D-1048")
    for _ in range(5):
        ch.outcome(af.CHOICE, "park", True)
        ch.outcome(af.CHOICE, "pan+5", True)
    ch.save()
    state_low = [22.2, 8.8, 5.5, 23.9, -24.6, 58.0]
    seen_candidates = []

    class _Cell:
        def act(self, cmd):
            if cmd == "state":
                return {"ok": True, "state": list(state_low), "target": list(state_low), "holding": False}
            if cmd == "park":
                return {"ok": True, "settled": True, "state": list(HOME_B), "target": list(HOME_B)}
            return {"ok": True, "state": list(state_low), "target": list(state_low)}

    def _look(frames):
        seen_candidates.append(frames[1] if len(frames) > 1 else frames[0])
        return {"clear": False, "low": [], "high": []} if False else {"clear": True, "low": [], "high": []}

    out = af.recover(
        _Cell(), HOME_B, 48.8, plan=lambda s: [s, HOME_B], look=_look,
        reserve=lambda _f: {"ok": True}, release=lambda: None,
        release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: True,
        order=lambda n: ch.ranked(af.CHOICE, n), tcp_x_m=0.0740, clear_z_m=0.10, extended_detours=True, sleep=lambda _s: None,
    )
    assert out["result"] == "folded" and out["candidate"] == "lift_then_park"


def test_build_multi_site_look_deduplicates_tiers_and_avoids_gap_false_positives():
    import cell_place_fit

    class _Cell:
        def __init__(self, img):
            self.img = img

        def frame(self, _cam):
            return self.img

    # 1) Tier expansion must NOT 4x-inflate two 750px slivers past MIN_SITE_AREA_PX (2500)
    sliver_cfg, _ = cell_place_fit.with_tiers({"sites": {
        "a": {"surface_z": 0.0, "surface_px": [[290, 260], [320, 260], [320, 285], [290, 285]], "surface_lab": [150, 128, 128]},
        "b": {"surface_z": 0.0, "surface_px": [[290, 100], [320, 100], [320, 125], [290, 125]], "surface_lab": [150, 128, 128]},
    }})
    img_sliv = np.full((400, 400, 3), 150, np.uint8)
    look_sliv = crp.build_multi_site_look(_Cell(img_sliv), sliver_cfg, {}, "a", ROI, None, _to_px, 0.0740)
    ext_hi_1, ext_hi_2 = [-25.0, -20.0, 0.0, 50.0, 0.0, 48.0], [25.0, -20.0, 0.0, 50.0, 0.0, 48.0]
    hi_frames = crp.interpolate_pose(ext_hi_1, ext_hi_2, max_step=2.0)
    res_sliv = look_sliv(hi_frames)
    assert not res_sliv["clear"] and res_sliv["off_surface"] > 0

    # 2) Valid calibrated white mats over dark workbench gap: empty dark gap does NOT produce false 'high' hits
    multi_cfg, _ = cell_place_fit.with_tiers({"sites": {
        "a": {"surface_z": 0.0, "surface_px": [[210, 250], [390, 250], [390, 350], [210, 350]], "surface_lab": [240, 128, 128]},
        "b": {"surface_z": 0.0, "surface_px": [[210, 50], [390, 50], [390, 150], [210, 150]], "surface_lab": [240, 128, 128]},
    }})
    img_gap = np.full((400, 400, 3), 50, np.uint8)
    img_gap[250:350, 210:390] = 240
    img_gap[50:150, 210:390] = 240
    look_gap = crp.build_multi_site_look(_Cell(img_gap), multi_cfg, {}, "a", ROI, None, _to_px, 0.0740)
    assert look_gap(hi_frames)["clear"] is True
    # Foreign object sitting inside the dark inter-site gap still blocks the high transit lane
    img_gap_obs = img_gap.copy()
    img_gap_obs[180:220, 310:350] = [20, 20, 220]
    res_gap_obs = crp.build_multi_site_look(_Cell(img_gap_obs), multi_cfg, {}, "a", ROI, None, _to_px, 0.0740)(hi_frames)
    assert not res_gap_obs["clear"] and len(res_gap_obs["high"]) >= 1
    # Adding a red box on calibrated site_b still blocks the high transit lane
    img_gap[80:120, 285:325] = [20, 20, 220]
    res_obs = crp.build_multi_site_look(_Cell(img_gap), multi_cfg, {}, "a", ROI, None, _to_px, 0.0740)(hi_frames)
    assert not res_obs["clear"] and len(res_obs["high"]) >= 1
