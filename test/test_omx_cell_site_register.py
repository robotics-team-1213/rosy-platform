"""cell_site_register: registered slots stay refused (SITE_NOT_MEASURED) until a passing post_eval; jobs never move the arm."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_spec as spec  # noqa: E402
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
        out += [refusal(sites, tmp, f"ship-h1r{0}-l{t - 1}", t), refusal(sites, f"ship-h1r0-l{t - 1}", tmp, t)]
    return out


@pytest.fixture
def cell(tmp_path):
    cfg = tmp_path / "cell-arm-a-stack.json"
    cfg.write_text(json.dumps({"arm": "arm_a", "sites": BASE}, indent=2), encoding="utf-8")
    ev = tmp_path / "candidates.json"
    ev.write_text('{"ship-h1r0": "cad"}', encoding="utf-8")
    return cfg, ev


def post_eval_report(site="ship-h1r0", place=SHIP["place"], status="pass", resid=3.2, **row):
    return {"schema": "rosy.omx-post-eval.v1", "measured": "2026-11-26T01:00:00+00:00", "verdict": "ok",
            "results": [{"site": site, "point_m": list(place), "status": status, "accepted": True, "residual_mag_mm": resid, **row}]}


def write_report(path, report):
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return path


def sites_of(cfg):
    return json.loads(cfg.read_text(encoding="utf-8"))["sites"]


def test_refusal_gate_unverified_refused_measured_and_legacy_pass():
    legacy = {**BASE, "ship-h1r0": dict(SHIP, status="measured"), "tmp-a-1": dict(TMP)}  # no status key: legacy, unchanged
    assert pairs(legacy) == [None] * 6
    unverified = {**legacy, "ship-h1r0": dict(SHIP, status="unverified")}
    assert all(r == "SITE_NOT_MEASURED" for r in pairs(unverified))
    assert refusal({**legacy, "tmp-a-1": dict(TMP, status="unverified")}, "tmp-a-1", "pallet-l0", 1) == "SITE_NOT_MEASURED"
    assert refusal({**legacy, "tmp-a-1": dict(TMP, status="stale")}, "belt", "tmp-a-1", 1) == "SITE_NOT_MEASURED"
    assert pairs({**BASE}) == ["SITE_NOT_CALIBRATED"] * 6  # missing stays a different code
    assert refusal(BASE, "belt", "pallet-l0", 1) is None and refusal(BASE, "belt", "temp_plate_a", 1) is None


def test_register_then_unverified_refused_then_promote_opens(cell, tmp_path):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    reg.register(cfg, "arm_a", "tmp-a-1", evidence=ev, operator="op", proposer="pr", **TMP)
    e = sites_of(cfg)["ship-h1r0"]
    assert e["status"] == "unverified" and e["provenance"]["source"] == "cad" and len(e["provenance"]["evidence"]["sha256"]) == 64
    assert all(r == "SITE_NOT_MEASURED" for r in pairs(sites_of(cfg)))
    pe = write_report(tmp_path / "pe.json", post_eval_report("ship-h1r0"))
    reg.promote(cfg, "arm_a", "ship-h1r0", pe, operator="op", proposer="pr")
    e = sites_of(cfg)["ship-h1r0"]
    assert e["status"] == "measured" and e["provenance"]["post_eval"]["error_mm"] == 3.2 and e["provenance"]["post_eval"]["operator"] == "op"
    assert "SITE_NOT_MEASURED" in pairs(sites_of(cfg))  # tmp-a-1 is still unverified
    reg.promote(cfg, "arm_a", "tmp-a-1", write_report(tmp_path / "pe2.json", post_eval_report("tmp-a-1", TMP["place"], resid=9.9)))
    assert pairs(sites_of(cfg)) == [None] * 6
    with pytest.raises(reg.RegisterError, match="already measured"):
        reg.promote(cfg, "arm_a", "ship-h1r0", pe)


def test_overwrite_refused_replace_keeps_history_and_resets_status(cell, tmp_path):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    before = cfg.read_bytes()
    with pytest.raises(reg.RegisterError, match="already exists"):
        reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    assert cfg.read_bytes() == before
    reg.promote(cfg, "arm_a", "ship-h1r0", write_report(tmp_path / "pe.json", post_eval_report()))
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, replace=True, **dict(SHIP, surface_z=-0.007))
    e = sites_of(cfg)["ship-h1r0"]
    assert e["surface_z"] == -0.007 and e["status"] == "unverified"
    assert e["history"][0]["entry"]["surface_z"] == -0.006 and e["history"][0]["entry"]["status"] == "measured"


def test_register_checks_inputs_and_leaves_file_untouched(cell, tmp_path):
    cfg, ev = cell
    before = cfg.read_bytes()
    for kw, text in (({"site": "ship-h1r0-l1"}, "base name"), ({"arm": "arm_b"}, "belongs to"), ({"map_from": "nope"}, "not a site"),
                     ({"source": "post_eval"}, "source must be"), ({"evidence": tmp_path / "missing"}, "not found"),
                     ({"tier_step_m": 0.5}, "tier_step_m"), ({"surface_z": float("nan")}, "finite")):
        args = {"arm": "arm_a", "site": "ship-h1r0", "evidence": ev, **SHIP, **kw}
        with pytest.raises(reg.RegisterError, match=text):
            reg.register(cfg, args.pop("arm"), args.pop("site"), **args)
    assert cfg.read_bytes() == before and not Path(str(cfg) + ".bak").exists()


@pytest.mark.parametrize(("mutate", "text"), [
    (lambda r: r.update(schema="other"), "schema"),
    (lambda r: r["results"][0].update(status="drift"), "not pass"),
    (lambda r: r["results"][0].update(accepted=False), "not pass"),
    (lambda r: r["results"][0].update(residual_mag_mm=25), "outside"),
    (lambda r: r["results"][0].update(residual_mag_mm=True), "finite"),
    (lambda r: r["results"][0].update(point_m=[0.3, 0.3]), "registered place"),
    (lambda r: r["results"][0].update(site="tmp-a-1"), "no row"),
    (lambda r: r["results"].append({**r["results"][0], "status": "skipped"}), "not pass"),
])
def test_promote_refuses_report_that_does_not_prove_the_slot(cell, tmp_path, mutate, text):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    report = post_eval_report()
    mutate(report)
    with pytest.raises(reg.RegisterError, match=text):
        reg.promote(cfg, "arm_a", "ship-h1r0", write_report(tmp_path / "pe.json", report))
    assert sites_of(cfg)["ship-h1r0"]["status"] == "unverified"
    with pytest.raises(reg.RegisterError, match="not registered by this tool"):
        reg.promote(cfg, "arm_a", "pallet", write_report(tmp_path / "pe.json", post_eval_report("pallet")))


def test_promote_reads_the_report_from_a_job_log(cell, tmp_path):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    log = tmp_path / "job.log"
    log.write_text("warming up {not json}\n" + json.dumps(post_eval_report(), indent=1) + "\n", encoding="utf-8")
    reg.promote(cfg, "arm_a", "ship-h1r0", log)
    assert sites_of(cfg)["ship-h1r0"]["status"] == "measured"
    log.write_text("no report here\n", encoding="utf-8")
    reg.register(cfg, "arm_a", "tmp-a-1", evidence=ev, **TMP)
    with pytest.raises(reg.RegisterError, match="schema"):
        reg.promote(cfg, "arm_a", "tmp-a-1", log)


def test_write_is_atomic_keeps_bak_and_follows_symlink(cell, tmp_path, monkeypatch):
    cfg, ev = cell
    reg.register(cfg, "arm_a", "ship-h1r0", evidence=ev, **SHIP)
    bak = json.loads(Path(str(cfg) + ".bak").read_text(encoding="utf-8"))["sites"]
    assert "ship-h1r0" not in bak and not list(tmp_path.glob("*.tmp"))
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


def test_cli_exit_codes_and_dry_run(cell, tmp_path, capsys):
    cfg, ev = cell
    base = ["register", "--config", str(cfg), "--arm", "arm_a", "--site", "ship-h1r0", "--place", "0.1281", "0.0286", "--surface-z", "-0.006",
            "--yaw-deg", "0", "--tier-step-m", "0.0324", "--map-from", "pallet", "--source", "cad", "--evidence", str(ev)]
    before = cfg.read_bytes()
    assert reg.main([*base, "--dry-run"]) == 0 and cfg.read_bytes() == before
    assert reg.main(base) == 0 and reg.main(base) == 2
    pe = write_report(tmp_path / "pe.json", post_eval_report(status="drift"))
    assert reg.main(["promote", "--config", str(cfg), "--arm", "arm_a", "--site", "ship-h1r0", "--post-eval", str(pe)]) == 2
    assert sites_of(cfg)["ship-h1r0"]["status"] == "unverified"


def _ok_params(job):
    common = {"arm": "arm_a", "config": "cell-arm-a-stack.json", "site": "ship-h1r0", "operator": "alice", "proposer": "bob"}
    if job == "site_register":
        return {**common, "x": 0.1281, "y": 0.0286, "surface_z": -0.006, "yaw_deg": 0, "tier_step_m": 0.0324,
                "map_from": "pallet", "source": "cad", "evidence": "candidates.json"}
    return {**common, "post_eval": "cell-job-api/abc.log"}


@pytest.mark.parametrize("job", ["site_register", "site_promote"])
def test_site_jobs_do_not_move_the_arm_and_need_distinct_actors(tmp_path, job):
    (tmp_path / "cell-arm-a-stack.json").write_text("{}", encoding="utf-8")
    j = spec.JOBS[job]
    params = _ok_params(job)
    assert not spec.moves_arm(j, params) and not j.get("moving") and not j.get("camera")
    argv = spec.build_argv(j, params, tmp_path)
    assert argv[:2] == ["bash", "-c"] and "cell_site_register.py" in argv and "--commissioning" not in argv and "--person-at-switch" not in argv
    assert job.split("_")[1] in argv
    assert "--replace" not in argv
    if job == "site_register":
        assert "--replace" in spec.build_argv(j, {**params, "replace": True}, tmp_path)
    with pytest.raises(ValueError, match="D-1024"):
        spec.build_argv(j, {**params, "operator": "Bob"}, tmp_path)
    for missing in ("operator", "proposer", "site", "arm"):
        with pytest.raises(ValueError, match="missing param"):
            spec.build_argv(j, {k: v for k, v in params.items() if k != missing}, tmp_path)
    for bad in ({"arm": "arm_s"}, {"config": "../x.json"}, {"site": "A B"}):
        with pytest.raises(ValueError):
            spec.build_argv(j, {**params, **bad}, tmp_path)
    with pytest.raises(ValueError, match="evidence|post_eval"):
        spec.build_argv(j, {**params, "evidence" if job == "site_register" else "post_eval": "/etc/passwd"}, tmp_path)
