"""cell_site_register: registered slots stay refused (SITE_NOT_MEASURED) on every motion path until XY and Z are both measured."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_spec as spec  # noqa: E402
import cell_config_io  # noqa: E402
import cell_place_fit  # noqa: E402
import cell_site_register as reg  # noqa: E402
import cell_site_target as cst  # noqa: E402

BASE = {"belt": {"surface_z": -0.0661},
        "pallet": {"place": [0.115, 0.034], "surface_z": -0.004, "yaw_deg": 0.0, "tier_step_m": 0.0345},
        "temp_plate_a": {"place": [0.034, 0.207], "surface_z": -0.004, "yaw_deg": -75.0, "tier_step_m": 0.0324}}
SHIP = {"place": [0.1281, 0.0286], "surface_z": -0.006, "yaw_deg": 0.0, "tier_step_m": 0.0324, "map_from": "pallet", "source": "cad"}
TMP = {"place": [-0.0653, 0.2034], "surface_z": -0.004, "yaw_deg": -75.0, "tier_step_m": 0.0324, "map_from": "temp_plate_a", "source": "cad"}


def refusal(sites, src, dst, tier):
    s = cst.resolve_cell_ab_site(src, None, allow_belt_temp=True, allow_pallet_src=True)
    d = cst.resolve_cell_ab_site(dst, tier, allow_belt_temp=False)
    return cst.calibration_refusal(sites, s["sim_site"] if s else src, d["sim_site"] if d else dst, tier)


def pairs(sites):
    out = []
    for t in (1, 2, 3):
        tmp = "tmp-a-1" if t == 1 else f"tmp-a-1-l{t - 1}"
        out += [refusal(sites, tmp, f"ship-h1r0-l{t - 1}", t), refusal(sites, f"ship-h1r0-l{t - 1}", tmp, t)]
    return out


@pytest.fixture
def cell(tmp_path):
    cfg = tmp_path / "cell-arm-a-stack.json"
    cfg.write_text(json.dumps({"arm": "arm_a", "sites": BASE}, indent=2), encoding="utf-8")
    ev = tmp_path / "candidates.json"
    ev.write_text('{"ship-h1r0": "cad"}', encoding="utf-8")
    return cfg, ev


def sites_of(cfg):
    return json.loads(Path(cfg).read_text(encoding="utf-8"))["sites"]


def write(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return Path(path)


def xy_report(cfg, site="ship-h1r0", arm="arm_a", age_s=0.0, status="pass", resid=3.2, **over):
    e = sites_of(cfg)[site]
    rep = {"schema": "rosy.omx-post-eval.v1", "arm": arm, "site_digest": {site: cst.site_digest(e)},
           "measured": (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat(timespec="seconds"), "verdict": "ok",
           "results": [{"site": site, "point_m": list(e["place"]), "status": status, "accepted": True, "residual_mag_mm": resid}]}
    return {**rep, **over}


def z_receipt(cfg, site="ship-h1r0", arm="arm_a", z=-0.0071, age_s=0.0, **over):
    e = sites_of(cfg)[site]
    rec = {"result": "touched", "surface_z": z, "site": site, "xy": list(e["place"]), "sets_surface_z": True,
           "measured": time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - age_s)), "touches_m": [z - 0.0001, z + 0.0001],
           "contact_binding": {"arm": arm, "site": site, "place": list(e["place"]), "yaw_deg": e["yaw_deg"]}}
    return {**rec, **over}


def registered(cell, site="ship-h1r0", fields=SHIP, **kw):
    cfg, ev = cell
    reg.register(cfg, "arm_a", site, evidence=ev, **fields, **kw)
    return cfg


def test_refusal_gate_unverified_refused_measured_and_legacy_pass():
    legacy = {**BASE, "ship-h1r0": dict(SHIP, status="measured"), "tmp-a-1": dict(TMP)}  # no status key: legacy, unchanged
    assert pairs(legacy) == [None] * 6
    assert all(r == "SITE_NOT_MEASURED" for r in pairs({**legacy, "ship-h1r0": dict(SHIP, status="unverified")}))
    assert refusal({**legacy, "tmp-a-1": dict(TMP, status="unverified")}, "tmp-a-1", "pallet-l0", 1) == "SITE_NOT_MEASURED"
    assert refusal({**legacy, "tmp-a-1": dict(TMP, status="stale")}, "belt", "tmp-a-1", 1) == "SITE_NOT_MEASURED"
    assert pairs({**BASE}) == ["SITE_NOT_CALIBRATED"] * 6
    assert refusal(BASE, "belt", "pallet-l0", 1) is None and refusal(BASE, "belt", "temp_plate_a", 1) is None


def test_live_cell_configs_have_no_status_key_so_legacy_means_absent():
    # checked read-only on the cell PC (2026-11-26): cell-arm-a/b-stack.json carry no free-form status; the rule is key presence
    assert cst.unmeasured_refusal({"pallet": {"place": [0, 0], "surface_z": 0}}, "pallet") is None
    assert cst.unmeasured_refusal({"x": {"status": "calibrated"}}, "x") == "SITE_NOT_MEASURED"


def test_shared_gate_follows_tier_of_and_with_tiers_does_not_copy_status():
    sites = {"ship-h1r0": dict(SHIP, status="unverified", provenance={"a": 1}, history=[], measured_xy={})}
    tiered = cell_place_fit.with_tiers({"sites": sites})[0]["sites"]
    assert "status" not in tiered["ship-h1r0-l1"] and "provenance" not in tiered["ship-h1r0-l1"]
    assert cst.unmeasured_refusal(tiered, "ship-h1r0-l1") == "SITE_NOT_MEASURED" and cst.unmeasured_refusal(tiered, "belt", "nowhere") is None
    sites["ship-h1r0"] = dict(SHIP, status="measured")  # a hand entry without evidence keys; promotion is seen by every tier at once
    assert cst.unmeasured_refusal(cell_place_fit.with_tiers({"sites": sites})[0]["sites"], "ship-h1r0-l2") is None


def _unverified_config(tmp_path):
    sites = {"belt": {"surface_z": -0.0661, "place": [0.0, 0.1], "yaw_deg": 0.0, "auto_roi": [0, 0, 10, 10]}, "pallet": BASE["pallet"],
             "ship-h1r0": {**SHIP, "status": "unverified", "provenance": {"tool": reg.TOOL}}}
    return {"arm_id": "arm_a", "sites": sites, "work_dir": str(tmp_path)}


@pytest.mark.parametrize(("src", "dst"), [("belt", "ship-h1r0-l0"), ("belt", "ship-h1r0"), ("ship-h1r0-l1", "pallet"), ("ship-h1r0", "belt")])
def test_auto_pick_stops_before_any_camera_or_arm_step(tmp_path, monkeypatch, src, dst):
    import cell_auto_pick as ap
    cell = Mock()
    out = ap._run_auto_core(cell, _unverified_config(tmp_path), {}, tmp_path / "cal.json", [], None, src, dst, tmp_path, None,
                            False, None, print, None, None, None, {})
    assert out["result"] == "refused" and out["error"] == "SITE_NOT_MEASURED" and cell.method_calls == []
    monkeypatch.setattr(ap.cell_auto_evidence, "map_pose_preflight", lambda *a, **k: "reached preflight")
    cfg = _unverified_config(tmp_path)
    cfg["sites"]["ship-h1r0"] = dict(SHIP, status="measured")
    assert ap._run_auto_core(cell, cfg, {}, tmp_path / "cal.json", [], None, src, dst, tmp_path, None,
                             False, None, print, None, None, None, {})["result"] == "held: reached preflight"
    dry = ap._run_auto_core(cell, _unverified_config(tmp_path), {}, tmp_path / "cal.json", [], None, src, dst, tmp_path, None,
                            True, None, print, None, None, None, {})
    assert dry["result"] == "held: reached preflight"  # a dry run commands no arm, so measuring plans may look at the slot


def test_taught_goal_checks_goal_site_and_destination_and_source(tmp_path):
    import cell_policy_handoff as ph
    cfg = _unverified_config(tmp_path)
    for goal, dest, src in (("pallet", "ship-h1r0-l0", "belt"), ("ship-h1r0-l0", "pallet", "belt"), ("pallet", "pallet", "ship-h1r0")):
        with pytest.raises(ValueError, match="SITE_NOT_MEASURED"):
            ph.validate_taught_goal(cfg, src, goal, dest, {})


def test_return_held_task_runner_and_taught_goal_refuse_too(tmp_path):
    import cell_policy_handoff as ph
    import cell_return_held as rh
    import cell_task_runner as tr
    cfg = _unverified_config(tmp_path)
    cell = Mock()
    out = rh.run_return_held(cell, cfg, {}, tmp_path / "cal.json", [], None, "ship-h1r0-l0", tmp_path)
    assert out["result"] == "refused" and out["error"] == "SITE_NOT_MEASURED" and cell.method_calls == []
    cfg_file = write(tmp_path / "cell-a.json", cfg)
    carry = Mock()
    task = {"schema": tr.SCHEMA, "task_id": "t1", "kind": "move", "from": "belt", "to": "ship-h1r0-l0"}
    res = tr.run_task(task, cfg_file, tmp_path / "catalog.json", tmp_path, carry=carry)
    assert res["status"] == "refused", res
    assert "SITE_NOT_MEASURED" in res["why"] and carry.call_count == 0
    with pytest.raises(ValueError, match="SITE_NOT_MEASURED"):
        ph.validate_taught_goal(cfg, "belt", "ship-h1r0-l0", "ship-h1r0-l0", {})


def test_register_then_unverified_refused_then_both_measurements_open(cell, tmp_path):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    reg.register(cfg, "arm_a", "tmp-a-1", evidence=ev, operator="op", proposer="pr", **TMP)
    e = sites_of(cfg)["ship-h1r0"]
    assert e["status"] == "unverified" and e["provenance"]["source"] == "cad" and len(e["provenance"]["evidence"]["sha256"]) == 64
    assert all(r == "SITE_NOT_MEASURED" for r in pairs(sites_of(cfg)))
    # XY alone is not enough
    reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy.json", xy_report(cfg)), operator="op", proposer="pr")
    e = sites_of(cfg)["ship-h1r0"]
    assert e["status"] == "unverified" and "measured_xy" in e and "measured_z" not in e and e["measured_xy"]["operator"] == "op"
    assert "SITE_NOT_MEASURED" in pairs(sites_of(cfg))
    # Z (adopts the touched height, which makes the earlier XY report stale) then a fresh XY report
    reg.promote(cfg, "arm_a", "ship-h1r0", z_evidence=write(tmp_path / "z.json", z_receipt(cfg, z=-0.0071)))
    e = sites_of(cfg)["ship-h1r0"]
    assert e["status"] == "unverified" and e["surface_z"] == -0.0071 and "measured_xy" not in e and e["measured_z"]["previous_surface_z"] == -0.006
    reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy2.json", xy_report(cfg)))
    assert sites_of(cfg)["ship-h1r0"]["status"] == "measured"
    reg.promote(cfg, "arm_a", "tmp-a-1", z_evidence=write(tmp_path / "z2.json", z_receipt(cfg, "tmp-a-1", z=-0.0042)))
    reg.promote(cfg, "arm_a", "tmp-a-1", post_eval=write(tmp_path / "xy3.json", xy_report(cfg, "tmp-a-1", resid=9.9)))
    assert pairs(sites_of(cfg))[:2] == [None, None]  # tier 1 only; tiers 2 and 3 need a tier step
    assert all(r == "SITE_NOT_MEASURED" for r in pairs(sites_of(cfg))[2:4])
    with pytest.raises(reg.RegisterError, match="already measured"):
        reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=tmp_path / "xy2.json")


def tier_receipt(cfg, layer, step=None, site="ship-h1r0"):
    e = sites_of(cfg)[site]
    name = f"{site}-l{layer}"
    z = e["surface_z"] + layer * (e["tier_step_m"] if step is None else step)
    return {**z_receipt(cfg, site, z=z), "site": name, "contact_binding": {"arm": "arm_a", "site": name, "place": list(e["place"]), "yaw_deg": e["yaw_deg"]}}


def measured_slot(cell, tmp_path, site="ship-h1r0", fields=SHIP):
    cfg = registered(cell, site, fields)
    reg.promote(cfg, "arm_a", site, z_evidence=write(tmp_path / "z.json", z_receipt(cfg, site, z=fields["surface_z"] - 0.001)))
    reg.promote(cfg, "arm_a", site, post_eval=write(tmp_path / "xy.json", xy_report(cfg, site)))
    assert sites_of(cfg)[site]["status"] == "measured"
    return cfg


def test_measured_slot_closes_when_place_yaw_height_or_step_change_afterwards(cell, tmp_path):
    cfg = measured_slot(cell, tmp_path)
    assert refusal(sites_of(cfg), "belt", "ship-h1r0-l0", 1) is None
    for key, value in (("surface_z", -0.0123), ("place", [0.13, 0.03]), ("yaw_deg", 5.0), ("tier_step_m", 0.04)):  # calibrate, hand edit
        sites = sites_of(cfg)
        sites["ship-h1r0"][key] = value
        assert refusal(sites, "belt", "ship-h1r0-l0", 1) == "SITE_NOT_MEASURED", key
        assert cst.unmeasured_refusal(sites, "ship-h1r0") == "SITE_NOT_MEASURED"
    sites = sites_of(cfg)
    sites["ship-h1r0"]["measured_z"]["digest"] = "0" * 16
    assert cst.unmeasured_refusal(sites, "ship-h1r0") == "SITE_NOT_MEASURED"
    del sites["ship-h1r0"]["measured_xy"]  # status says measured, the evidence is gone
    assert cst.unmeasured_refusal(sites, "ship-h1r0-l0") == "SITE_NOT_MEASURED"


def test_layers_one_and_two_open_only_with_a_measured_tier_step(cell, tmp_path):
    cfg = measured_slot(cell, tmp_path)
    sites = sites_of(cfg)
    assert cst.unmeasured_refusal(sites, "ship-h1r0", "ship-h1r0-l0") is None
    tiered = cell_place_fit.with_tiers({"sites": sites})[0]["sites"]
    assert cst.unmeasured_refusal(tiered, "ship-h1r0-l0") is None
    assert cst.unmeasured_refusal(tiered, "ship-h1r0-l1") == cst.unmeasured_refusal(sites, "ship-h1r0-l2") == "SITE_NOT_MEASURED"
    assert [refusal(sites, "belt", f"ship-h1r0-l{t - 1}", t) for t in (1, 2, 3)] == [None, "SITE_NOT_MEASURED", "SITE_NOT_MEASURED"]
    with pytest.raises(reg.RegisterError, match="gives a step"):  # 8 mm off the registered 32.4 mm
        reg.promote(cfg, "arm_a", "ship-h1r0", tier_evidence=write(tmp_path / "t.json", tier_receipt(cfg, 1, step=SHIP["tier_step_m"] + 0.008)))
    with pytest.raises(reg.RegisterError, match="must be a touch of"):
        reg.promote(cfg, "arm_a", "ship-h1r0", tier_evidence=write(tmp_path / "t.json", z_receipt(cfg)))
    e = reg.promote(cfg, "arm_a", "ship-h1r0", tier_evidence=write(tmp_path / "t.json", tier_receipt(cfg, 2)))  # allowed after measured
    assert e["status"] == "measured" and e["measured_tier_step"]["layer"] == 2
    sites = sites_of(cfg)
    tiered = cell_place_fit.with_tiers({"sites": sites})[0]["sites"]
    assert cst.unmeasured_refusal(tiered, "ship-h1r0-l1", "ship-h1r0-l2") is None
    assert [refusal(sites, "belt", f"ship-h1r0-l{t - 1}", t) for t in (1, 2, 3)] == [None] * 3
    sites["ship-h1r0"]["surface_z"] += 0.002  # a later height change closes the tiers too
    assert cst.unmeasured_refusal(sites, "ship-h1r0-l1") == "SITE_NOT_MEASURED"


def test_evidence_records_job_id_and_sha(cell, tmp_path):
    cfg = registered(cell)
    logs = tmp_path / "cell-job-api"
    logs.mkdir()
    log = logs / "20261126-101500-abc123.log"
    log.write_text(json.dumps(xy_report(cfg)), encoding="utf-8")
    rec = reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=log)["measured_xy"]
    assert rec["job_id"] == "20261126-101500-abc123" and len(rec["sha256"]) == 64
    assert reg.promote(cfg, "arm_a", "ship-h1r0", z_evidence=write(tmp_path / "z.json", z_receipt(cfg)))["measured_z"]["job_id"] is None


def test_config_io_rewrite_keeps_evidence_of_a_promote_made_meanwhile(cell, tmp_path):
    import cell_config_io as cio
    cfg = registered(cell)
    stale = json.loads(cfg.read_text())  # what calibrate read at its start, before the promote below
    reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy.json", xy_report(cfg)))
    stale["sites"]["ship-h1r0"]["surface_z"] = -0.0091  # calibrate's surface step
    stale["sites"]["pallet"]["note"] = "regions moved"
    reg.register(cfg, "arm_a", "tmp-a-1", evidence=cell[1], **TMP)  # registered after calibrate started
    stale2 = {k: v for k, v in stale.items()}
    cio.write_config(cfg, stale2, indent=1, changed={"ship-h1r0": ("surface_z",)})
    now = sites_of(cfg)
    assert now["ship-h1r0"]["surface_z"] == -0.0091 and "measured_xy" in now["ship-h1r0"] and now["pallet"]["note"] == "regions moved"
    assert now["tmp-a-1"]["status"] == "unverified"
    assert cst.unmeasured_refusal(now, "ship-h1r0") == "SITE_NOT_MEASURED"  # the new height has no measurement yet


def test_config_io_is_the_writer_calibrate_and_surface_use():
    root = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"
    for name in ("cell_calibrate.py", "cell_surface.py", "cell_site_register.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "cell_config_io" in text and "cfg_tmp" not in text and "args.config.write_text" not in text, name


def test_both_evidences_in_one_call_and_nothing_to_promote(cell, tmp_path):
    cfg = registered(cell)
    with pytest.raises(reg.RegisterError, match="needs --z-evidence"):
        reg.promote(cfg, "arm_a", "ship-h1r0")
    z = write(tmp_path / "z.json", z_receipt(cfg))
    after_z = dict(sites_of(cfg)["ship-h1r0"], surface_z=-0.0071)
    xy = write(tmp_path / "xy.json", {**xy_report(cfg), "site_digest": {"ship-h1r0": cst.site_digest(after_z)}})
    assert reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=xy, z_evidence=z)["status"] == "measured"


def test_register_refuses_legacy_reserved_and_unknown_names_even_with_replace(cell):
    cfg, ev = cell
    before = cfg.read_bytes()
    for name in ("pallet", "belt", "beltend", "temp_plate_a", "temp_plate_b", "stand", "plate_b", "stack", "yard-x", "ship-h9r9"):
        for replace in (False, True):
            with pytest.raises(reg.RegisterError, match="designated slot"):
                reg.register(cfg, "arm_a", name, evidence=ev, replace=replace, **SHIP)
    with pytest.raises(reg.RegisterError, match="designated slot"):
        reg.register(cfg, "arm_a", "tmp-b-1", evidence=ev, **SHIP)  # arm_b's slot
    assert cfg.read_bytes() == before
    assert cst.designated_slot_arms("ship-h1r0") == ("arm_a", "arm_b") and cst.designated_slot_arms("tmp-a-1") == ("arm_a",)


def test_replace_only_what_this_tool_wrote(cell, tmp_path):
    cfg, ev = cell
    data = json.loads(cfg.read_text())
    data["sites"]["ship-h1r1"] = {"place": [0.1, 0.1], "surface_z": -0.005}  # hand calibrated, no provenance
    cfg.write_text(json.dumps(data))
    with pytest.raises(reg.RegisterError, match="not registered by this tool"):
        reg.register(cfg, "arm_a", "ship-h1r1", evidence=ev, replace=True, **SHIP)
    assert sites_of(cfg)["ship-h1r1"] == {"place": [0.1, 0.1], "surface_z": -0.005}


def test_overwrite_refused_replace_keeps_history_and_resets_measurements(cell, tmp_path):
    cfg = registered(cell)
    ev = cell[1]
    before = cfg.read_bytes()
    with pytest.raises(reg.RegisterError, match="already exists"):
        reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    assert cfg.read_bytes() == before
    reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy.json", xy_report(cfg)))
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, replace=True, **dict(SHIP, surface_z=-0.007))
    e = sites_of(cfg)["ship-h1r0"]
    assert e["surface_z"] == -0.007 and e["status"] == "unverified" and "measured_xy" not in e
    assert e["history"][0]["entry"]["surface_z"] == -0.006 and "measured_xy" in e["history"][0]["entry"]


def test_register_checks_inputs_and_leaves_file_untouched(cell, tmp_path):
    cfg, ev = cell
    before = cfg.read_bytes()
    for kw, text in (({"site": "ship-h1r0-l1"}, "base name"), ({"arm": "arm_b", "site": "tmp-a-1"}, "designated slot"),
                     ({"map_from": "nope"}, "not a site"), ({"source": "post_eval"}, "source must be"),
                     ({"evidence": tmp_path / "missing"}, "not found"), ({"tier_step_m": 0.5}, "tier_step_m"),
                     ({"surface_z": float("nan")}, "finite")):
        args = {"arm": "arm_a", "site": "ship-h1r0", "evidence": ev, **SHIP, **kw}
        with pytest.raises(reg.RegisterError, match=text):
            reg.register(cfg, args.pop("arm"), args.pop("site"), **args)
    assert cfg.read_bytes() == before and not list(tmp_path.glob("*.bak-*"))


@pytest.mark.parametrize(("make", "text"), [
    (lambda c: xy_report(c, schema="other"), "schema"),
    (lambda c: xy_report(c, arm="arm_b"), "arm 'arm_b'"),
    (lambda c: xy_report(c, site_digest={}), "was not made for"),
    (lambda c: xy_report(c, site_digest={"ship-h1r0": "0" * 16}), "was not made for"),
    (lambda c: xy_report(c, age_s=3600), "older than the registration"),
    (lambda c: xy_report(c, status="drift"), "not pass"),
    (lambda c: xy_report(c, resid=25), "outside"),
    (lambda c: {**xy_report(c), "results": []}, "no row"),
    (lambda c: {k: v for k, v in xy_report(c).items() if k != "arm"}, "arm None"),
])
def test_promote_refuses_xy_report_that_does_not_prove_this_entry(cell, tmp_path, make, text):
    cfg = registered(cell)
    with pytest.raises(reg.RegisterError, match=text):
        reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "pe.json", make(cfg)))
    assert sites_of(cfg)["ship-h1r0"]["status"] == "unverified" and "measured_xy" not in sites_of(cfg)["ship-h1r0"]


def test_old_report_does_not_promote_replaced_values(cell, tmp_path):
    cfg = registered(cell)
    old = write(tmp_path / "old.json", xy_report(cfg))
    time.sleep(0.02)
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=cell[1], replace=True, **dict(SHIP, surface_z=-0.0065))
    with pytest.raises(reg.RegisterError, match="was not made for"):  # its digest is for the old height
        reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=old)


@pytest.mark.parametrize(("make", "text"), [
    (lambda c: z_receipt(c, result="no contact"), "completed touch"),
    (lambda c: z_receipt(c, arm="arm_b"), "not bound"),
    (lambda c: {**z_receipt(c), "site": "ship-h1r1"}, "completed touch"),
    (lambda c: z_receipt(c, xy=[0.2, 0.2]), "another place"),
    (lambda c: z_receipt(c, age_s=7200), "older than the registration"),
    (lambda c: z_receipt(c, touches_m=[-0.0071]), "at least two"),
    (lambda c: z_receipt(c, touches_m=[-0.0071, -0.0171]), "disagree"),
    (lambda c: z_receipt(c, z=0.9), "disagree"),
    (lambda c: z_receipt(c, sets_surface_z=False), "completed touch"),
])
def test_promote_refuses_z_receipt_that_does_not_prove_this_entry(cell, tmp_path, make, text):
    cfg = registered(cell)
    with pytest.raises(reg.RegisterError, match=text):
        reg.promote(cfg, "arm_a", "ship-h1r0", z_evidence=write(tmp_path / "z.json", make(cfg)))
    assert sites_of(cfg)["ship-h1r0"]["surface_z"] == -0.006 and "measured_z" not in sites_of(cfg)["ship-h1r0"]


def test_promote_only_what_this_tool_registered(cell, tmp_path):
    cfg = registered(cell)
    with pytest.raises(reg.RegisterError, match="not a designated slot"):
        reg.promote(cfg, "arm_a", "pallet", post_eval=write(tmp_path / "pe.json", xy_report(cfg, "ship-h1r0")))


def test_promote_reads_the_report_from_a_job_log(cell, tmp_path):
    cfg = registered(cell)
    log = tmp_path / "job.log"
    log.write_text("warming up {not json}\n" + json.dumps(xy_report(cfg), indent=1) + "\n", encoding="utf-8")
    assert reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=log)["measured_xy"]["rows"] == 1
    log.write_text("no report here\n", encoding="utf-8")
    reg.register(cfg, "arm_a", "tmp-a-1", evidence=cell[1], **TMP)
    with pytest.raises(reg.RegisterError, match="schema"):
        reg.promote(cfg, "arm_a", "tmp-a-1", post_eval=log)


def test_write_is_atomic_keeps_mode_prunes_backups_and_follows_symlink(cell, tmp_path, monkeypatch):
    cfg, ev = cell
    cfg.chmod(0o640)
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    assert (cfg.stat().st_mode & 0o777) == 0o640 and not list(tmp_path.glob("*.tmp"))
    baks = sorted(tmp_path.glob("cell-arm-a-stack.json.bak-*"))
    assert len(baks) == 1 and "ship-h1r0" not in json.loads(baks[0].read_text())["sites"]
    for name in ("ship-h1r1", "ship-h1r2", "ship-h2r0", "ship-h2r1", "ship-h2r2"):
        reg.register(cfg, "arm_a", name, evidence=ev, **SHIP)
    assert len(list(tmp_path.glob("cell-arm-a-stack.json.bak-*"))) == cell_config_io.KEEP_BACKUPS
    before = cfg.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        reg.register(cfg, "arm_a", "tmp-a-1", evidence=ev, **TMP)
    assert cfg.read_bytes() == before and not list(tmp_path.glob("*.tmp"))
    monkeypatch.undo()
    real = tmp_path / "real"
    real.mkdir()
    target = real / "cell-arm-a-stack.json"
    target.write_bytes(before)
    link = tmp_path / "cell-link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    reg.register(link, "arm_a", "tmp-a-1", evidence=ev, **TMP)
    assert link.is_symlink() and "tmp-a-1" in sites_of(target)


def test_write_refuses_when_another_writer_changed_the_file(cell):
    cfg, _ = cell
    before = cfg.read_bytes()
    with pytest.raises(reg.RegisterError, match="changed while"):
        reg.atomic_write(cfg, "{}", expect_sha="0" * 64)
    assert cfg.read_bytes() == before


def test_config_lock_blocks_a_second_writer(cell, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    cfg, ev = cell
    monkeypatch.setattr(cell_config_io, "LOCK_TIMEOUT_S", 0.2)
    with open(str(cfg) + ".lock", "a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        with pytest.raises(reg.RegisterError, match="locked by another writer"):
            reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    assert "ship-h1r0" not in sites_of(cfg)
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)


def test_cli_exit_codes_and_dry_run(cell, tmp_path):
    cfg, ev = cell
    base = ["register", "--config", str(cfg), "--arm", "arm_a", "--site", "ship-h1r0", "--place", "0.1281", "0.0286", "--surface-z", "-0.006",
            "--yaw-deg", "0", "--tier-step-m", "0.0324", "--map-from", "pallet", "--source", "cad", "--evidence", str(ev)]
    before = cfg.read_bytes()
    assert reg.main([*base, "--dry-run"]) == 0 and cfg.read_bytes() == before
    assert reg.main(base) == 0 and reg.main(base) == 2
    pe = write(tmp_path / "pe.json", xy_report(cfg, status="drift"))
    assert reg.main(["promote", "--config", str(cfg), "--arm", "arm_a", "--site", "ship-h1r0", "--post-eval", str(pe)]) == 2
    assert reg.main(["promote", "--config", str(cfg), "--arm", "arm_a", "--site", "ship-h1r0"]) == 2
    assert sites_of(cfg)["ship-h1r0"]["status"] == "unverified"


def _ok_params(job):
    common = {"arm": "arm_a", "config": "cell-arm-a-stack.json", "site": "ship-h1r0", "operator": "alice", "proposer": "bob"}
    if job == "site_register":
        return {**common, "x": 0.1281, "y": 0.0286, "surface_z": -0.006, "yaw_deg": 0, "tier_step_m": 0.0324,
                "map_from": "pallet", "source": "cad", "evidence": "candidates.json"}
    return {**common, "post_eval": "cell-job-api/abc.log", "z_evidence": "surface-ship-h1r0.json"}


@pytest.mark.parametrize("job", ["site_register", "site_promote"])
def test_site_jobs_do_not_move_the_arm_need_distinct_actors_and_refuse_symlinks(tmp_path, job):
    for name in ("cell-arm-a-stack.json", "candidates.json", "surface-ship-h1r0.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "cell-job-api").mkdir()
    (tmp_path / "cell-job-api" / "abc.log").write_text("{}", encoding="utf-8")
    j = spec.JOBS[job]
    params = _ok_params(job)
    assert not spec.moves_arm(j, params) and not j.get("moving") and not j.get("camera")
    argv = spec.build_argv(j, params, tmp_path)
    assert argv[:2] == ["bash", "-c"] and "cell_site_register.py" in argv and "--commissioning" not in argv and "--person-at-switch" not in argv
    assert job.split("_")[1] in argv and "--replace" not in argv
    if job == "site_promote":
        assert "--post-eval" in argv and "--z-evidence" in argv
    else:
        assert "--replace" in spec.build_argv(j, {**params, "replace": True}, tmp_path)
    with pytest.raises(ValueError, match="D-1024"):
        spec.build_argv(j, {**params, "operator": "Bob"}, tmp_path)
    for missing in ("operator", "proposer", "site", "arm"):
        with pytest.raises(ValueError, match="missing param"):
            spec.build_argv(j, {k: v for k, v in params.items() if k != missing}, tmp_path)
    for bad in ({"arm": "arm_s"}, {"config": "../x.json"}, {"site": "A B"}):
        with pytest.raises(ValueError):
            spec.build_argv(j, {**params, **bad}, tmp_path)
    key = "evidence" if job == "site_register" else "post_eval"
    with pytest.raises(ValueError, match="workdir|safe relative"):
        spec.build_argv(j, {**params, key: "/etc/passwd"}, tmp_path)
    with pytest.raises(ValueError, match="no such file"):
        spec.build_argv(j, {**params, key: "missing.json"}, tmp_path)
    link = tmp_path / "link.json"
    try:
        link.symlink_to("/etc/hostname")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValueError, match="symlink"):
        spec.build_argv(j, {**params, key: "link.json"}, tmp_path)


def test_site_surface_job_measures_a_registered_slot_under_the_existing_surface_guards(tmp_path):
    (tmp_path / "cell-arm-a-stack.json").write_text('{"sites": {}}', encoding="utf-8")
    j = spec.JOBS["site_surface"]
    params = {"arm": "arm_a", "config": "cell-arm-a-stack.json", "site": "ship-h1r0", "surface_clear": True}
    assert j["moving"] and j["camera"] and spec.moves_arm(j, params)
    with pytest.raises(ValueError, match="person_at_switch"):  # the D-911 guard of the other surface job still applies
        spec.build_argv(j, params, tmp_path)
    argv = spec.build_argv(j, {**params, "person_at_switch": True}, tmp_path)
    assert argv[-2:] == ["--commissioning", "--person-at-switch"]
    assert argv[argv.index("--remeasure-surface") + 1] == "ship-h1r0" and "--surface-clear" in argv and "--only" in argv
    with pytest.raises(ValueError, match="surface_clear"):
        spec.build_argv(j, {**params, "surface_clear": False, "person_at_switch": True}, tmp_path)
    with pytest.raises(ValueError, match="missing param"):
        spec.build_argv(j, {k: v for k, v in params.items() if k != "surface_clear"}, tmp_path)


def test_the_order_z_then_xy_is_written_where_operators_read(cell, tmp_path):
    root = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"
    for name in ("AGENTS.md", "cell_site_register.py", "cell_site_job_spec.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "site_surface" in text and ("Z first" in text or "then Z" in text or "site_register -> site_surface" in text), name
    # XY first, then Z: the Z promotion changes surface_z, so the XY report no longer describes the entry and measured is not reached
    cfg = registered(cell)
    reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy.json", xy_report(cfg)))
    assert reg.promote(cfg, "arm_a", "ship-h1r0", z_evidence=write(tmp_path / "z.json", z_receipt(cfg)))["status"] == "unverified"
    assert reg.promote(cfg, "arm_a", "ship-h1r0", post_eval=write(tmp_path / "xy2.json", xy_report(cfg)))["status"] == "measured"


def test_source_tier_is_gated_like_the_destination_tier(cell, tmp_path):
    cfg = measured_slot(cell, tmp_path)
    sites = sites_of(cfg)
    assert [refusal(sites, f"ship-h1r0-l{t}", "pallet-l0", 1) for t in (0, 1, 2)] == [None, "SITE_NOT_MEASURED", "SITE_NOT_MEASURED"]
    reg.promote(cfg, "arm_a", "ship-h1r0", tier_evidence=write(tmp_path / "t.json", tier_receipt(cfg, 1)))
    assert [refusal(sites_of(cfg), f"ship-h1r0-l{t}", "pallet-l0", 1) for t in (0, 1, 2)] == [None, None, None]
    sites = sites_of(cfg)
    sites["ship-h1r0"]["surface_z"] += 0.002
    assert refusal(sites, "ship-h1r0-l1", "pallet-l0", 1) == "SITE_NOT_MEASURED"


def test_auto_pick_source_tier_needs_the_tier_step_too(cell, tmp_path, monkeypatch):
    import cell_auto_pick as ap
    cfg = measured_slot(cell, tmp_path)
    sites = {**sites_of(cfg), "belt": {"surface_z": -0.0661, "place": [0.0, 0.1], "yaw_deg": 0.0, "auto_roi": [0, 0, 10, 10]}}
    config = {"arm_id": "arm_a", "sites": sites, "work_dir": str(tmp_path)}
    monkeypatch.setattr(ap.cell_auto_evidence, "map_pose_preflight", lambda *a, **k: "reached preflight")
    run = lambda src: ap._run_auto_core(Mock(), config, {}, tmp_path / "c.json", [], None, src, "belt", tmp_path, None,  # noqa: E731
                                        False, None, print, None, None, None, {})
    assert run("ship-h1r0-l0")["result"] == "held: reached preflight"
    out = run("ship-h1r0-l1")
    assert out["result"] == "refused" and out["error"] == "SITE_NOT_MEASURED"


def test_rewrite_keeps_a_registered_slots_disk_geometry_unless_the_writer_names_the_key(cell, tmp_path):
    import cell_config_io as cio
    cfg = registered(cell)
    stale = json.loads(cfg.read_text())  # a calibrate run started here
    stale["sites"]["ship-h1r0"]["surface_px"] = [[1, 2], [3, 4]]  # a non-geometry key the writer owns
    stale["sites"]["pallet"]["surface_z"] = -0.0042  # a legacy site: the writer's value stays as before
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=cell[1], replace=True, **dict(SHIP, place=[0.14, 0.04], yaw_deg=3.0))
    cio.write_config(cfg, stale, indent=1)
    now = sites_of(cfg)["ship-h1r0"]
    assert now["place"] == [0.14, 0.04] and now["yaw_deg"] == 3.0 and now["surface_z"] == SHIP["surface_z"]  # the replace was not reverted
    assert now["surface_px"] == [[1, 2], [3, 4]] and now["history"] and sites_of(cfg)["pallet"]["surface_z"] == -0.0042
    stale["sites"]["ship-h1r0"]["surface_z"] = -0.0099
    cio.write_config(cfg, stale, indent=1, changed={"ship-h1r0": ("surface_z",)})
    assert sites_of(cfg)["ship-h1r0"]["surface_z"] == -0.0099 and sites_of(cfg)["ship-h1r0"]["place"] == [0.14, 0.04]


def test_a_failed_write_after_the_arm_moved_keeps_the_measured_height_in_a_sidecar(cell, tmp_path, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    import cell_config_io as cio
    cfg = registered(cell)
    before = cfg.read_bytes()
    config = json.loads(before)
    config["sites"]["ship-h1r0"]["surface_z"] = -0.0088
    monkeypatch.setattr(cio, "LOCK_TIMEOUT_S", 0.2)
    done = [{"surface ship-h1r0": "touched", "surface_z": -0.0088}, {"surface tmp-a-1": "no contact", "surface_z": None}]
    with open(str(cfg) + ".lock", "a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        err = cio.write_config_checked(cfg, config, 1, done)
    assert err and "locked by another writer" in err and "saved in" in err and cfg.read_bytes() == before
    side = list(tmp_path.glob("cell-arm-a-stack.json.unwritten-*.json"))
    assert len(side) == 1 and json.loads(side[0].read_text())["surface_z"] == {"ship-h1r0": -0.0088}
    assert cio.write_config_checked(cfg, config, 1, done) is None and sites_of(cfg)["ship-h1r0"]["surface_z"] == -0.0088
