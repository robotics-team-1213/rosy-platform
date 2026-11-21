"""omx_loop: stage order, preset propagation, manifests, the live-store and no-arm/no-ssh guards (stub runner), plus rank->offer->ingest for real."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools/sim"), str(ROOT / "deploy/robot/omx"), str(ROOT / "test")]
import omx_loop as loop  # noqa: E402

SCRIPTS = [loop.R2S, loop.SWEEP, loop.TWIN, loop.JOIN]
REAL_JOIN = (ROOT / loop.JOIN).exists()  # read before the fixture swaps loop.ROOT


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A tool root holding empty stand-ins for every CLI (the deploy CLIs may be absent on this branch) and a recording runner."""
    root = tmp_path / "root"
    for s in SCRIPTS:
        (root / s).parent.mkdir(parents=True, exist_ok=True)
        (root / s).write_text("")
    monkeypatch.setattr(loop, "ROOT", root)
    cap = tmp_path / "capture"
    cap.mkdir()
    (cap / "capture.json").write_text("{}")
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    (sweep / "meta.json").write_text("{}")
    att = tmp_path / "attempts.jsonl"
    att.write_text("{}\n")
    ep = tmp_path / "ep1"
    ep.mkdir()
    calls = []

    def runner(argv):
        calls.append([str(t) for t in argv])
        if loop.JOIN in str(argv[1]).replace("\\", "/"):
            return 0, json.dumps({"joined": [dict(attempt={}, episode=dict(id="ep1", path=str(ep), sha="x"), status="ok"),
                                             dict(attempt={}, episode=dict(id="ep2", path="/gone", sha=None), status="missing_folder")]})
        return 0, "{}"
    return dict(tmp=tmp_path, cap=cap, sweep=sweep, att=att, calls=calls, runner=runner)


def subs(calls):
    return [(Path(c[1]).name, c[2]) for c in calls]


def args(f, stage, *extra):
    return [stage, "--run-dir", str(f["tmp"] / "run"), "--capture", str(f["cap"]), "--sweep", str(f["sweep"]),
            "--store", str(f["tmp"] / "review-choices.json"), "--cell", "cell.yaml", *extra]


def test_default_is_a_plan_that_runs_and_writes_nothing(fake, capsys):
    loop.main(args(fake, "all", "--prev", "old.json"), runner=fake["runner"])
    assert fake["calls"] == [] and not (fake["tmp"] / "run").exists()
    out = capsys.readouterr().out
    assert "measure" in out and "offers" in out and loop.PRESET in out


def test_all_runs_the_stages_in_order_with_one_preset(fake):
    loop.main(args(fake, "all", "--run", "--prev", "old.json", "--attempts", str(fake["att"]), "--episodes", "eps", "--local-twin"), runner=fake["runner"])
    assert subs(fake["calls"]) == [("omx_real2sim.py", "measure"), ("omx_real2sim.py", "diff"), ("omx_carry_sweep.py", "rank"),
                                   ("omx_carry_sweep.py", "offers"), ("cell_attempt_episodes.py", str(fake["att"])), ("omx_carry_sweep.py", "ingest"),
                                   ("omx_twin.py", "replay"), ("omx_twin.py", "report"), ("omx_real2sim.py", "measure"), ("omx_real2sim.py", "diff")]
    calls = fake["calls"]
    for c in calls:
        if c[1].endswith("omx_real2sim.py"):
            assert c[c.index("--preset") + 1] == loop.PRESET
    ingest = calls[5]
    assert ingest[ingest.index("--joined") + 1] == str(fake["tmp"] / "run/04-ingest/joined.json")
    assert ingest[ingest.index("--episodes") + 1] == str(fake["tmp"] / "ep1") and ingest[-3:-1] != ["--episodes", "/gone"]  # only the ok episode
    assert "/gone" not in ingest
    second = calls[-2]  # the second measure takes the twin folder and dr_next; its diff compares with the first snapshot
    assert "--twin" in second and "--dr-next" in second
    assert calls[-1][2] == "diff" and "01-r2s" in calls[-1][3] and calls[-1][3].endswith("snapshot.json")
    assert any(c[2] == "replay" and c[3] == str(fake["tmp"] / "ep1") for c in calls)


def test_preset_and_choices_reach_sim_and_sweep_run(fake):
    loop.main(args(fake, "rank", "--run", "--run-sweep", "--snapshot", "s.json", "--preset", "p9", "--choice", "frame=x"), runner=fake["runner"])
    sim, run = fake["calls"][0], fake["calls"][1]
    assert sim[2] == "sim" and sim[sim.index("--preset") + 1] == "p9" and "frame=x" in sim
    assert run[2] == "run" and "preset=p9" in run and "frame=x" in run


def test_all_binds_ranking_and_offers_to_the_snapshot_it_just_measured(fake):
    loop.main(args(fake, "all", "--run", "--run-sweep"), runner=fake["runner"])
    measure, evaluate, rank, offer = fake["calls"]
    snapshot = str(Path(measure[3]) / "snapshot.json")
    for command, action in ((evaluate, "run"), (rank, "rank"), (offer, "offers")):
        assert command[2] == action
        assert command[command.index("--snapshot") + 1] == snapshot


def test_local_twin_stops_before_feedback_when_no_episodes_join(fake):
    def runner(argv):
        fake["calls"].append([str(t) for t in argv])
        return 0, '{"joined": []}'

    with pytest.raises(SystemExit, match="no verified episodes"):
        loop.main(args(fake, "twin", "--run", "--local-twin", "--attempts", str(fake["att"])), runner=runner)
    assert [Path(c[1]).name for c in fake["calls"]] == ["cell_attempt_episodes.py"]


def test_manifest_has_inputs_digests_commands_outputs_and_sha(fake):
    loop.main(args(fake, "r2s", "--run", "--prev", "old.json"), runner=fake["runner"])
    m = json.loads((fake["tmp"] / "run/01-r2s/manifest.json").read_text())
    assert m["stage"] == "r2s" and m["preset"] == loop.PRESET and "code_sha" in m
    assert m["inputs"][0]["path"] == str(fake["cap"]) and len(m["inputs"][0]["sha256"]) == 16
    assert [c["argv"][2] for c in m["commands"]] == ["measure", "diff"] and all(c["rc"] == 0 for c in m["commands"])
    assert [o["path"].endswith(("snapshot.json", "diff.json")) for o in m["outputs"]] == [True, True]
    assert (fake["tmp"] / "run/01-r2s/capture/capture.json").exists() and not (fake["cap"] / "snapshot.json").exists()  # the recorded capture is untouched
    (fake["cap"] / "capture.json").write_text('{"x":1}')
    assert loop.digest(fake["cap"]) != m["inputs"][0]["sha256"]


def test_live_site_store_is_refused_even_with_legacy_flag(fake):
    live = fake["tmp"] / "site" / "configured-cell-state" / "choices.json"
    a = ["offer", "--run-dir", str(fake["tmp"] / "run"), "--sweep", str(fake["sweep"]), "--store", str(live), "--run"]
    with pytest.raises(SystemExit, match="live site"):
        loop.main(a, runner=fake["runner"])
    assert fake["calls"] == []
    with pytest.raises(SystemExit, match="live site"):
        loop.main(a + ["--site-store"], runner=fake["runner"])
    assert fake["calls"] == []


@pytest.mark.parametrize("argv", [
    ["ssh", "rosy-cell", "ls"], ["python", loop.R2S, "capture"], ["python", loop.TWIN, "batch"], ["python", loop.TWIN, "live"],
    ["python", "deploy/robot/omx/cell_auto_pick.py"], ["python", "deploy/robot/omx/omx_arm.py", "move"], ["python", loop.R2S, "request", "belt"],
    ["python", loop.R2S, "pipeline"], ["C:/Windows/System32/OpenSSH/ssh.exe", "x"],
])
def test_no_arm_no_ssh_guard(argv):
    with pytest.raises(SystemExit):
        loop.guard(argv)


def test_every_command_a_full_loop_issues_passes_the_guard_and_names_no_host(fake):
    loop.main(args(fake, "all", "--run", "--prev", "old.json", "--attempts", str(fake["att"])), runner=fake["runner"])
    for c in fake["calls"]:
        loop.guard(c)
        assert not any(t in ("ssh", "scp", "--site") for t in c)


def test_a_missing_deploy_cli_fails_clearly(fake):
    (loop.ROOT / loop.JOIN).unlink()
    with pytest.raises(SystemExit, match="not on this branch"):
        loop.main(args(fake, "ingest", "--run", "--attempts", str(fake["att"])), runner=fake["runner"])
    assert fake["calls"] == []


def test_a_failing_command_stops_the_stage_and_keeps_a_manifest(fake):
    with pytest.raises(SystemExit, match="returned 3"):
        loop.main(args(fake, "rank", "--run"), runner=lambda argv: (3, ""))
    assert json.loads((fake["tmp"] / "run/01-rank/manifest.json").read_text())["commands"][0]["rc"] == 3


def test_rank_offer_ingest_for_real_on_tiny_fixtures(tmp_path):
    import omx_carry_sweep as sw
    import test_omx_carry_sweep as t
    t._fake_sweep(tmp_path)
    att = t._attempts(tmp_path, [dict(attempt_id="a1", outcome="placed"), dict(attempt_id="a2", outcome="failed", fail_stage="grasp")])
    store, run = tmp_path / "store" / "review-choices.json", tmp_path / "run"
    (tmp_path / "meta.json").write_text(json.dumps(dict(tiers=[2], search_ids=[0, 1, 2], dr=sw.DR, sha="", choices={"preset": t.P})))
    assert loop.main(["rank", "--run-dir", str(run), "--sweep", str(tmp_path), "--run"]) == 0
    assert loop.main(["offer", "--run-dir", str(run), "--sweep", str(tmp_path), "--store", str(store), "--run"]) == 0
    assert store.exists()
    if REAL_JOIN:  # the join CLI lives on the tier-proof branch; without it the loop refuses (tested above) and the sweep's own ingest runs
        loop.main(["ingest", "--run-dir", str(run), "--sweep", str(tmp_path), "--attempts", str(att), "--run"])
    else:
        sw.ingest(tmp_path, att)
    assert (tmp_path / "real_outcomes.jsonl").exists() and (tmp_path / "dr_next.json").exists()
    assert json.loads((run / "01-rank/manifest.json").read_text())["commands"][0]["rc"] == 0


def gate_args(f, *extra):
    return args(f, "gate", "--fit", "fit.json", "--candidate", "c1", "--base-stack", "b.json", "--stack", "s.json", "--grasp", "g.jsonl", *extra)


def gate_inputs(fake, real=True, trials=True):
    for name, on in (("real_outcomes.jsonl", real), ("trials.jsonl", trials)):
        if on:
            (fake["sweep"] / name).write_text(json.dumps(dict(attempt_id="a1", candidate="c1", tier=2, outcome="ok")) + "\n")  # no physics tag
    (loop.ROOT / loop.SYSID).parent.mkdir(parents=True, exist_ok=True)
    (loop.ROOT / loop.SYSID).write_text("")


def test_gate_runs_sysid_task_with_the_sweep_and_untagged_real_rows(fake):
    gate_inputs(fake)
    loop.main(gate_args(fake, "--run"), runner=fake["runner"])
    c = fake["calls"][0]
    assert subs(fake["calls"]) == [("omx_sysid.py", "task")] and c[c.index("--real") + 1].endswith("real_outcomes.jsonl")
    assert c[c.index("--sweep") + 1] == str(fake["sweep"])
    assert (fake["tmp"] / "run/01-gate/manifest.json").exists()


@pytest.mark.parametrize("have", [dict(real=False), dict(trials=False)])
def test_gate_stops_when_the_sweep_lacks_trials_or_real_outcomes(fake, have):
    gate_inputs(fake, **have)
    with pytest.raises(SystemExit, match="gate stopped"):
        loop.main(gate_args(fake, "--run"), runner=fake["runner"])
    assert fake["calls"] == []


def test_all_puts_gate_after_ingest_only_with_fit(fake):
    gate_inputs(fake)
    loop.main(args(fake, "all", "--run", "--attempts", str(fake["att"]), "--fit", "fit.json", "--candidate", "c1", "--base-stack", "b",
                   "--stack", "s", "--grasp", "g"), runner=fake["runner"])
    names = [c[2] if c[2] in ("task", "ingest") else None for c in fake["calls"]]
    assert names.index("task") == names.index("ingest") + 1


def test_fresh_measures_without_prev_but_still_diffs(fake):
    loop.main(args(fake, "r2s", "--run", "--prev", "old.json", "--fresh"), runner=fake["runner"])
    measure, diff = fake["calls"]
    assert "--prev" not in measure and diff[3] == "old.json"


def test_default_preset_is_the_physical_cell_and_cad190_stays_a_named_preset():
    import omx_two_arm_sites as sites
    assert loop.PRESET == "v24-20261114-cad194" and sites.PRESETS[loop.PRESET]["arm_bases"] == "cad-194"
    assert sites.PRESETS["v24-20261114-cad190"]["arm_bases"] == "cad-190"


@pytest.fixture
def remote(fake, monkeypatch):
    """The twin stage's remote path with a stub runner: no git commit is made, the 'host' writes twin.json where remote_sim fetches it."""
    staged, runs = [], []
    monkeypatch.setattr(loop, "stage_files", lambda repo, sha, files, prefix, tag: staged.append((files, prefix)) or "wipsha")
    (fake["tmp"] / "ep1" / "top").mkdir()
    (fake["tmp"] / "ep1" / "top" / "0.jpg").write_bytes(b"x")
    (fake["tmp"] / "ep1" / "ticks.jsonl").write_text("{}")
    inner = fake["runner"]

    def runner(argv):
        if loop.REMOTE_SIM in str(argv[1]).replace("\\", "/"):
            runs.append([str(t) for t in argv])
            out = Path(argv[argv.index("--log-dir") + 1]) / "out" / "twin"
            (out / "ep1").mkdir(parents=True)
            (out / "ep1" / "twin.json").write_text('{"episode": "ep1"}')
            (out / "report.md").write_text("# twin")
            return 0, ""
        return inner(argv)
    fake["runner"] = runner
    return dict(fake, staged=staged, runs=runs)


def test_twin_ships_the_joined_episodes_runs_remotely_and_brings_twin_json_back(remote):
    loop.main(args(remote, "twin", "--run", "--attempts", str(remote["att"]), "--episodes", "eps"), runner=remote["runner"])
    files, prefix = remote["staged"][0]
    assert sorted(files) == [f"{prefix}ep1/ticks.jsonl", f"{prefix}ep1/top/0.jpg"]  # only the ok episode, under one prefix
    (run,) = remote["runs"]
    assert run[run.index("--host") + 1] == "ai" and run[run.index("--sha") + 1] == "wipsha" and not any(c[2] == "replay" for c in remote["calls"])
    assert "omx_twin.py replay" in run[-1] and "omx_twin.py report" in run[-1] and f"{prefix}$e" in run[-1]
    d0 = remote["tmp"] / "run/02-twin"
    assert (d0 / "ep1/twin.json").exists() and (d0 / "report.md").read_text() == "# twin"
    assert (d0 / "manifest.json").exists()


def test_twin_stops_when_no_twin_json_comes_back(remote):
    remote["runner"] = lambda argv: (0, "{}") if loop.REMOTE_SIM not in str(argv[1]).replace("\\", "/") else (0, "")
    with pytest.raises(SystemExit, match="no twin.json came back"):
        loop.main(args(remote, "twin", "--run", "--attempts", str(remote["att"]), "--episodes", "eps"), runner=remote["runner"])


@pytest.mark.parametrize("host", ["rosy-arm-cell", "site", "robttt@100.1.2.3"])
def test_the_remote_guard_allows_sim_roles_only_never_a_cell_or_site_host(host):
    loop.guard([sys.executable, loop.REMOTE_SIM, "--host", "model", "--sha", "x", "cmd", "--", "true"])
    with pytest.raises(loop.Refused):
        loop.guard([sys.executable, loop.REMOTE_SIM, "--host", host, "--sha", "x", "cmd", "--", "true"])
    with pytest.raises(SystemExit):
        loop.build(["twin", "--run-dir", "r", "--cell", "c", "--twin-host", host])


def test_twin_plan_prints_the_remote_command_and_ships_nothing(remote, capsys):
    loop.main(["twin", "--run-dir", str(remote["tmp"] / "run"), "--cell", "c.json", "--attempts", str(remote["att"])], runner=remote["runner"])
    assert remote["staged"] == [] and remote["runs"] == [] and "remote_sim.py --host ai" in capsys.readouterr().out
