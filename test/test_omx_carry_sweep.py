"""The carry sweep's pure parts: sampling, judging classes, ranking into cell_choices offers, and the real-result ingest (no MuJoCo)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT / "tools/sim"), str(ROOT / "deploy/robot/omx")]
import cell_choices  # noqa: E402
import omx_carry_sweep as sw  # noqa: E402

P = "v24-20261114-cad194"


def test_candidates_stay_in_bounds_and_include_both_baselines():
    c = sw.sample_candidates(12, 3)
    assert len(c) == 12 and {"sim-default", "real-default"} <= set(c)
    for name, p in c.items():
        assert set(p) == set(sw.BOUNDS)
        if name.startswith("c"):
            assert all(lo <= p[k] <= hi for k, (lo, hi) in sw.BOUNDS.items())
    assert c == sw.sample_candidates(12, 3)


def test_dr_centres_tcp_on_v21_and_draws_sag_as_its_own_term():
    assert sw.DR["tcp_m"][len(sw.DR["tcp_m"]) // 2] == 0.0740 and max(abs(t - 0.0740) for t in sw.DR["tcp_m"]) <= 0.001
    assert min(sw.DR["sag_mm"]) >= 4.0 and max(sw.DR["sag_mm"]) <= 12.0 and 8.0 in sw.DR["sag_mm"]  # table 8.3 mm +-2 under FK 0, pose dependent
    sc = sw.draw_scenarios(60, 5, sw.DR)
    assert {s["sag_mm"] for s in sc} <= set(sw.DR["sag_mm"]) and len({s["sag_mm"] for s in sc}) > 1
    assert {s["tcp_m"] for s in sc} <= set(sw.DR["tcp_m"]) and sc == sw.draw_scenarios(60, 5, sw.DR)
    assert {s["sag_mm"] for s in sw.draw_scenarios(5, 5, {**sw.DR, "sag_mm": []})} == {0.0}  # an old --dr file has no sag term
    import omx_two_arm_kin as kin
    assert kin.norm_to_rad(sw.WRIST_FLEX_MAX_NORM) > kin.plan_values()[0][3]  # the cap leaves the home pose (norm 51.6) reachable


def test_wilson_and_run_classes():
    assert sw.wilson(0, 0) == [0.0, 1.0] and sw.wilson(9, 9)[0] > 0.6 and sw.wilson(9, 9)[1] == 1.0
    ok = dict(completed=True, rows=[dict(result="pass", held_tilt_max_deg=12.0)])
    assert sw.classify_run(ok, 30.0)[:2] == (True, None)
    slip = dict(completed=True, rows=[dict(result="pass", held_tilt_max_deg=31.0)])
    assert sw.classify_run(slip, 30.0)[1] == "carry:tilt_slip"
    crash = dict(completed=False, rows=[dict(result="fail", arm_link_contacts=["a~b"], first_contact_phase={"arm_other": "lower@frame9"})])
    assert sw.classify_run(crash, 30.0)[1] == "lower:collision"


def _fake_sweep(tmp_path):
    cands = {"good": dict(zip(sw.BOUNDS, (0.012, 0.004, 4.0))), "bad": dict(zip(sw.BOUNDS, (0.02, 0.0, 9.0))), "sim-default": sw.BASELINES["sim-default"], "real-default": sw.BASELINES["real-default"]}
    (tmp_path / "candidates.json").write_text(json.dumps(cands))
    rows = []
    for scen in list(range(3)) + list(range(1000, 1010)):
        for c in cands:
            ok = c == "good" or (c != "bad" and scen % 2 == 0)
            rows.append(dict(tier=2, cand=c, scen=scen, seed=scen, physics="design" if scen % 2 else "twin-kp-20261109", tcp_m=0.074 if scen % 3 else 0.0748,
                             sag_mm=8.0 if scen % 2 else 4.0, zero_deg=1.0, vision=False, ok=ok, cls=None if ok else "grasp:collision"))
    (tmp_path / "trials.jsonl").write_text("\n".join(map(json.dumps, rows)))
    return cands


def test_rank_writes_offers_cell_choices_accepts(tmp_path):
    _fake_sweep(tmp_path)
    res = sw.rank(tmp_path, {0, 1, 2}, [2], top=2, sha="abc1234567890", preset=P)
    assert res[2]["top"][0]["cand"] == "good" and res[2]["top"][0]["k"] == res[2]["top"][0]["n"] == 10
    assert res[2]["failure_histogram"] == {"grasp:collision": 20}
    ch = cell_choices.Choices(tmp_path / "offers.json")
    offered = ch.data["values"]["carry.tier2"]
    assert offered[0]["source"].startswith("sim:") and offered[0]["value"]["candidate"] == "good" and offered[0]["evidence"]["sim_n"] == 10
    assert ch.best("carry.tier2")["candidate"] in {c["value"]["candidate"] for c in offered}


def test_ingest_lists_missing_mechanisms_and_reweights(tmp_path):
    _fake_sweep(tmp_path)
    good = {"carry.tier2": dict(candidate="good")}
    rows = [dict(attempt_id="a1", to="tmp-a-1-l1", outcome="placed", context=dict(choices_used=good)),
            dict(attempt_id="a2", to="tmp-a-1-l1", outcome="failed", fail_stage="lift", context=dict(choices_used=good)),
            dict(attempt_id="a3", to="tmp-a-1-l1", outcome="placed", context=dict(choices_used=good))]
    att = tmp_path / "attempts.jsonl"
    att.write_text("\n".join(map(json.dumps, rows)))
    check = tmp_path / "check.json"
    check.write_text(json.dumps({"a1": True, "a3": False}))
    rep = sw.ingest(tmp_path, att, check)
    assert rep["real"]["good@t2"] == {"ok": 1, "lift": 1, "verify": 1}
    assert {m["real_phase"] for m in rep["missing_mechanisms"]} == {"lift", "verify"}  # sim never failed "good"
    assert set(rep["next_dr"]) == {"tcp_m", "sag_mm", "zero_deg", "physics", "vision_frac"}
    assert (tmp_path / "dr_next.json").exists()


def test_offers_merge_round_trips_through_the_store_and_never_touches_real_outcomes(tmp_path):
    _fake_sweep(tmp_path)
    sw.rank(tmp_path, {0, 1, 2}, [2], top=2, sha="abc1234567890", preset=P)
    store = tmp_path / "site" / "choices.json"
    assert sw.main(["offers", str(tmp_path), "--merge", str(store)]) == 0
    ch = cell_choices.Choices(store)
    assert [e["source"].startswith("sim:") for e in ch.data["values"]["carry.tier2"]] == [True, True]
    best = ch.best("carry.tier2")
    assert best["candidate"] == "good" and "site.place_dz_m" not in best and set(best) == {"candidate", "tier", "auto.grasp_depth_m", "place_dz", "auto.jaw_margin_mm"}
    assert ch.data["values"]["carry.tier2"][0]["evidence"]["sim_n"] == 10 and ch.data["values"]["carry.tier2"][0]["evidence"]["geometry_only"] == "D-947"
    ch.outcome("carry.tier2", best, False)  # one real failed try on the best one
    ch.save()
    once = store.read_text()
    assert sw.merge_offers(tmp_path, store) == dict(added=0, kept=2, store=str(store))  # idempotent
    assert store.read_text() == once
    ch = cell_choices.Choices(store)
    assert ch.data["values"]["carry.tier2"][0]["tries"] == 1 and ch.best("carry.tier2")["candidate"] != "good"  # real record outranks the sim order
    try:
        import cell_carry_choices as carry  # on the omx-tier-proof branch
    except ImportError:
        return
    config, applied, shadow = carry.apply({"params": {}, "sites": {"t": {}}}, ch, "t-l1", "t")
    assert applied and shadow is None and config["sites"]["t"]["place_dz"] == applied[1]["place_dz"]


def test_merge_refuses_other_or_missing_preset_and_writes_nothing(tmp_path):
    import pytest
    _fake_sweep(tmp_path)
    sw.rank(tmp_path, {0, 1, 2}, [2], top=2, sha="abc1234567890", preset="v24-old")
    store = tmp_path / "site" / "choices.json"
    with pytest.raises(ValueError, match="v24-old"):
        sw.merge_offers(tmp_path, store, P)
    assert sw.merge_offers(tmp_path, store, "v24-old")["added"] == 2  # the matching preset merges
    assert cell_choices.Choices(store).data["values"]["carry.tier2"][0]["evidence"]["preset"] == "v24-old"
    sw.rank(tmp_path, {0, 1, 2}, [2], top=2, sha="abc1234567890")  # no preset recorded
    other = tmp_path / "other.json"
    with pytest.raises(SystemExit, match="refused"):
        sw.main(["offers", str(tmp_path), "--merge", str(other), "--preset", P])
    assert not other.exists()


# the writers' real shapes: cell_area_zones z_gate (evaluate_signed_tier_residual_mm), cell_stack_check.check
Z_PASS = {"verdict": "PASS", "failure_code": None, "r_k_mm": -0.5, "expected_tier": 2}
Z_FAIL = {"verdict": "FAIL", "failure_code": "S6_UNSEATED_CONE", "r_k_mm": 2.0, "expected_tier": 2}
Z_UNKNOWN = {"verdict": "UNKNOWN", "failure_code": "S5_VIEW_OR_GATE_MISMATCH", "reason": "no measured post-release stack height"}
CHECK_OK = {"accepted": True, "tiers": {"1": {"ok": True}, "2": {"ok": True}}}
CHECK_BAD = {"accepted": False, "tiers": {"1": {"ok": True}, "2": {"ok": False, "long_error_mm": 4.0}}}
CHECK_NO_FLOOR = {"accepted": False, "reason": "empty slot floor not found: no depth", "tiers": {}}
CHECK_HIDDEN = {"accepted": False, "tiers": {"2": {"ok": False, "reason": "top face partly hidden: its size says nothing"}}}


def test_tier_verdict_maps_verified_true_failed_false_and_blind_never_true():
    tv = sw.tier_verdict
    assert [tv({"z_gate": Z_PASS, "verified": True}), tv({"z_gate": Z_FAIL, "verified": False}), tv(CHECK_OK), tv(CHECK_BAD), tv("REFUSED"), tv(True)] == [True, False, True, False, False, True]
    unknown = [{"z_gate": Z_UNKNOWN, "verified": False}, {"z_gate": Z_PASS, "verified": False}, CHECK_NO_FLOOR, CHECK_HIDDEN, "UNKNOWN", {}, None, {"verdict": "S5"}]
    assert [tv(u) for u in unknown] == [None] * len(unknown)


def _attempts(tmp_path, rows):
    good = {"carry.tier2": dict(candidate="good", physics="twin-kp-20261109")}
    lines = [dict(a, to="tmp-a-1-l1", context=dict(choices_used=good)) for a in rows]
    att = tmp_path / "attempts.jsonl"
    att.write_text("\n".join(map(json.dumps, lines)))
    return att


def test_ingest_reads_tier_proof_rows_counts_unknown_apart_and_tolerates_missing_episode_field(tmp_path):
    _fake_sweep(tmp_path)
    att = _attempts(tmp_path, [
        dict(attempt_id="a1", outcome="placed"),                       # PASS by attempt id
        dict(attempt_id="a2", outcome="placed", episode={"id": "ep-2", "path": "x", "sha": "y"}),  # PASS by episode id
        dict(attempt_id="a3", outcome="placed"),                       # FAIL
        dict(attempt_id="a4", outcome="placed"),                       # UNKNOWN verdict
        dict(attempt_id="a5", outcome="placed"),                       # no verdict at all
        dict(attempt_id="a6", outcome="failed", fail_stage="grasp"),   # a proof cannot rescue a failed attempt
    ])
    proof = tmp_path / "proof.jsonl"
    proof.write_text("\n".join(map(json.dumps, [
        dict(attempt_id="a1", z_gate=Z_PASS, verified=True), dict(episode_id="ep-2", **CHECK_OK),
        dict(attempt_id="a3", **CHECK_BAD), dict(attempt_id="a4", z_gate=Z_UNKNOWN, verified=False),
        dict(attempt_id="a6", **CHECK_OK)])))
    rep = sw.ingest(tmp_path, att, proof)
    assert rep["real"]["good@t2"] == {"ok": 2, "verify": 1, "grasp": 1}
    assert rep["real_unknown"] == {"good@t2": 2}  # a4 UNKNOWN, a5 no verdict
    out = [json.loads(x) for x in (tmp_path / "real_outcomes.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in out] == ["ok", "ok", "fail", "unknown", "unknown", "fail"] and all("physics" not in r for r in out)  # real rows carry no sim physics tag


def test_no_tier_proof_keeps_placed_unknown_and_a_mapping_file_still_reads(tmp_path):
    _fake_sweep(tmp_path)
    att = _attempts(tmp_path, [dict(attempt_id="a1", outcome="placed"), dict(attempt_id="a2", outcome="placed")])
    unknown = sw.Counter()
    assert not sw.real_table(att, unknown=unknown)
    assert unknown == {("good", 2): 2}
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"a1": True, "a2": "UNKNOWN"}))
    unknown = sw.Counter()
    assert sw.real_table(att, old, unknown)[("good", 2)] == {"ok": 1} and unknown == {("good", 2): 1}


def test_candidate_ingest_requires_original_episode_when_join_was_checked(tmp_path):
    from cell_attempt_episodes import episode_ref

    att = _attempts(tmp_path, [dict(attempt_id="a1", outcome="placed")])
    attempt = json.loads(att.read_text())
    episode = tmp_path / "episode"
    episode.mkdir()
    (episode / "ticks.jsonl").write_text("{}\n")
    (episode / "task.json").write_text('{"attempt_id": "a1"}')
    result = episode / "result.json"
    result.write_text("{}")
    proof = tmp_path / "proof.json"
    proof.write_text('{"a1": true}')
    joined = tmp_path / "joined.json"
    joined.write_text(json.dumps({"joined": [{"attempt": attempt, "episode": episode_ref(episode), "status": "ok"}]}))
    assert sw.real_rows(att, proof, joined=joined)[0]["outcome"] == "ok"
    result.write_text('{"changed": true}')
    assert sw.real_rows(att, proof, joined=joined)[0]["outcome"] == "unknown"


def test_shadowed_offer_is_counted_apart_and_never_credited(tmp_path):
    _fake_sweep(tmp_path)
    att = _attempts(tmp_path, [dict(attempt_id="a1", outcome="placed"),
                               dict(attempt_id="a2", outcome="placed", tried=dict(carry_shadowed=dict(offer="carry.tier2", candidate="good", keys=["grasp_depth_m"]))),
                               dict(attempt_id="a3", outcome="failed", tried=dict(carry_shadowed=dict(offer="carry.tier2", candidate="good", keys=["place_dz"])))])
    shadowed = sw.Counter()
    assert not sw.real_table(att, None, None, shadowed) and shadowed == {("good", 2): 2}
    rep = sw.ingest(tmp_path, att)
    assert rep["shadowed"] == {"good@t2": 2} and rep["real_unknown"] == {"good@t2": 1}
    assert [r["outcome"] for r in map(json.loads, (tmp_path / "real_outcomes.jsonl").read_text().splitlines())] == ["unknown", "shadowed", "shadowed"]
