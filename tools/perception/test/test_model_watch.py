"""D-373 decision 5: the site model watcher (new HF commit -> intake -> shadow push)."""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "tools" / "perception" / "model") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "perception" / "model"))

import watch  # noqa: E402

C1, C2, C3, C4 = "1" * 40, "2" * 40, "3" * 40, "4" * 40
ROBOTS = ["pinky-a", "pinky-b"]


def _config(tmp_path, **extra):
    doc = {
        "backend": "hf", "repo": "org/lane-seg",
        "robots": [{"name": "pinky-a", "host": "10.0.0.11"},
                   {"name": "pinky-b", "host": "10.0.0.12"}],
        "ssh": {"identity": "/etc/rosy/model-watch/id", "known_hosts": "/etc/rosy/model-watch/kh"},
        "intake_out": str(tmp_path / "models"),
        "state_file": str(tmp_path / "state.json"),
        "max_new_per_run": 2,
        **extra,
    }
    path = tmp_path / "model-watch.yaml"
    path.write_text(json.dumps(doc), encoding="utf-8")  # JSON is YAML
    return path


def _state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


def _seed(tmp_path, commits: dict, shadow=None):
    """A state file, so a run is not a bootstrap run."""
    order = {sha: i for i, sha in enumerate(commits)}
    doc = {"version": 1, "repo": "org/lane-seg", "next_order": len(commits),
           "commits": {sha: {"order": order[sha], **rec} for sha, rec in commits.items()},
           "shadow": shadow or {}}
    (tmp_path / "state.json").write_text(json.dumps(doc), encoding="utf-8")


# --- pure core ------------------------------------------------------------------------------

def test_plan_run_takes_unseen_and_retryable_commits_oldest_first():
    state = {"commits": {C2: {"intake": "pass"},
                         C3: {"intake": "error", "attempts": 2},
                         C4: {"intake": "error", "attempts": 5}}}
    assert watch.plan_run([C4, C3, C2, C1], state, limit=5, max_attempts=5) == [C1, C3]
    assert watch.plan_run([C4, C3, C2, C1], state, limit=1, max_attempts=5) == [C1]
    assert watch.plan_run([C3, C2, C1], {"commits": {}}, limit=0, max_attempts=5) == []
    assert watch.plan_run([], {}, limit=3, max_attempts=5) == []


def test_skip_old_bootstrap_keeps_only_the_newest():
    state = watch.new_state("org/m")
    new = watch.skip_old([C3, C2, C1], state, since=None, fresh=True)
    assert new["commits"][C1] == {"order": 0, "intake": "skipped", "reason": "bootstrap"}
    assert new["commits"][C2]["order"] == 1 and C3 not in new["commits"]
    assert watch.skip_old([C3, C2, C1], state, since=None, fresh=False) == state
    assert state["commits"] == {}  # pure


def test_skip_old_since_skips_at_and_before():
    state = watch.new_state("org/m")
    new = watch.skip_old([C4, C3, C2, C1], state, since=C2, fresh=True)
    assert {s: r["reason"] for s, r in new["commits"].items()} == {C1: "since", C2: "since"}
    # later runs: since may have slid out of the listed window once recorded
    assert watch.skip_old([C4, C3], new, since=C2, fresh=False) == new
    with pytest.raises(ValueError, match="since"):
        watch.skip_old([C4, C3], state, since=C2, fresh=False)


def test_apply_result_is_pure_and_keeps_order():
    state = watch.new_state("org/m")
    a = watch.apply_result(state, C1, {"intake": "error", "attempts": 1})
    b = watch.apply_result(a, C1, {"intake": "fail", "reasons": ["x"]})
    assert state["commits"] == {}
    assert b["commits"][C1] == {"order": 0, "intake": "fail", "reasons": ["x"]}
    assert b["next_order"] == 1


def _passed(order, robots):
    return {"order": order, "intake": "pass", "model_revision": f"rev-{order}",
            "robots": {n: {"status": st, "attempts": at} for n, (st, at) in robots.items()}}


def test_supersede_older_leaves_only_the_newest_pending():
    state = {"commits": {C1: _passed(1, {"pinky-a": ("pending", 1), "pinky-b": ("ok", 1)}),
                         C2: _passed(2, {"pinky-a": ("pending", 0)})}}
    new = watch.supersede_older(state)
    assert new["commits"][C1]["robots"]["pinky-a"]["status"] == "superseded"
    assert new["commits"][C1]["robots"]["pinky-b"]["status"] == "ok"
    assert new["commits"][C2]["robots"]["pinky-a"]["status"] == "pending"
    assert state["commits"][C1]["robots"]["pinky-a"]["status"] == "pending"  # pure


def test_record_delivery_counts_attempts_and_gives_up():
    state = {"commits": {C1: _passed(1, {"pinky-a": ("pending", 0)})}, "shadow": {}}
    s1 = watch.record_delivery(state, C1, "pinky-a", error="timeout", max_attempts=2)
    assert s1["commits"][C1]["robots"]["pinky-a"] == {
        "status": "pending", "attempts": 1, "last_error": "timeout"}
    s2 = watch.record_delivery(s1, C1, "pinky-a", error="timeout", max_attempts=2)
    assert s2["commits"][C1]["robots"]["pinky-a"]["status"] == "gave_up"
    ok = watch.record_delivery(s1, C1, "pinky-a", error=None, max_attempts=2)
    assert ok["commits"][C1]["robots"]["pinky-a"]["status"] == "ok"
    assert ok["shadow"]["pinky-a"] == {"sha": C1, "order": 1}
    assert state["commits"][C1]["robots"]["pinky-a"]["attempts"] == 0  # pure


# --- token: only the secret file -------------------------------------------------------------

def test_hf_token_only_from_the_secret_file(tmp_path):
    tok = tmp_path / "hf_token"
    tok.write_text("hf_file\n", encoding="utf-8")
    assert watch.read_hf_token({"HF_TOKEN_FILE": str(tok)}, {}) == "hf_file"
    assert watch.read_hf_token({}, {"hf_token_file": str(tok)}) == "hf_file"
    # HF_TOKEN in the environment is ignored; False stops huggingface_hub from
    # falling back to HF_TOKEN or $HF_HOME/token on its own
    assert watch.read_hf_token({"HF_TOKEN": "hf_env"}, {}) is False
    # the unit always names the file; absent means a public repo, not an error
    assert watch.read_hf_token({"HF_TOKEN_FILE": str(tmp_path / "missing")}, {}) is False
    with pytest.raises(SystemExit):  # there is no --token option
        watch.main(["--config", "x", "--token", "hf_x"])


def _fake_hub(monkeypatch):
    seen = {}

    class HfApi:
        def __init__(self, token=None):
            seen["api_token"] = token

        def list_repo_commits(self, repo, repo_type):
            seen["repo_type"] = repo_type
            return [types.SimpleNamespace(commit_id=C2), types.SimpleNamespace(commit_id=C1)]

    def snapshot_download(**kw):
        seen["download"] = kw
        return kw["local_dir"]

    hub = types.ModuleType("huggingface_hub")
    hub.HfApi, hub.snapshot_download = HfApi, snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    return seen


def test_no_token_file_passes_token_false_to_hf(monkeypatch, tmp_path):
    seen = _fake_hub(monkeypatch)
    assert watch.hf_list_commits("org/m", False) == [C2, C1]
    assert seen["api_token"] is False and seen["repo_type"] == "model"

    got = {}
    fake_intake = types.ModuleType("intake")
    fake_intake.DEFAULT_GATE, fake_intake.ROOT = "gate.yaml", "/repo"

    def run(source, **kw):
        got.update(kw, source=source)
        kw["downloader"](repo_id="org/m", revision=C1, local_dir="d")
        return 1, {"verdict": "fail"}

    fake_intake.run = run
    monkeypatch.setitem(sys.modules, "intake", fake_intake)
    cfg = watch.load_config(_config(tmp_path))
    watch.default_intake(cfg, False)(C1)
    assert got["source"] == f"hf:org/lane-seg@{C1}"
    assert seen["download"]["token"] is False


@pytest.mark.parametrize("change", [
    {"repo": "not-a-repo"},
    {"robots": []},
    {"robots": [{"name": "a b", "host": "h"}]},
    {"robots": [{"name": "a", "host": "h"}, {"name": "a", "host": "h2"}]},
    {"ssh": {"known_hosts": "/kh"}},  # the site key is required, no operator default
    {"max_new_per_run": 0},
    {"max_attempts": 0},
    {"since": "abc"},
    {"push_timeout_s": -1},
])
def test_bad_config_exits_2(tmp_path, change):
    cfg = _config(tmp_path, **change)
    assert watch.main(["--config", str(cfg)], list_commits=lambda *a: [C1],
                      intake_fn=None, deliver_fn=None, env={}) == 2


# --- one run, HF / intake / deliver injected -----------------------------------------------

class Fakes:
    def __init__(self, commits, verdict="pass", failing_robot=None, list_error=None,
                 intake_error=None):
        self.commits, self.verdict = commits, verdict
        self.failing_robot, self.list_error = failing_robot, list_error
        self.intake_error = intake_error
        self.listed, self.intakes, self.delivers = [], [], []
        self.shadow, self.hold, self.busy, self.observed = {}, {}, set(), []

    def observe(self, robot):
        self.observed.append(robot["name"])
        return {"shadow": self.shadow.get(robot["name"]), "hold": self.hold.get(robot["name"])}

    def list_commits(self, repo, token):
        self.listed.append((repo, token))
        if self.list_error:
            raise self.list_error
        return list(self.commits)

    def intake(self, sha):
        self.intakes.append(sha)
        if self.intake_error == "raise":
            raise OSError("disk full")
        rev = f"lane-seg-20260930-{sha[:8]}"
        if self.intake_error == "transient":
            return 1, {"verdict": "fail", "model_revision": None, "transient": True,
                       "reasons": ["OSError: HF unreachable"]}
        if self.verdict == "pass":
            return 0, {"verdict": "pass", "model_revision": rev, "reasons": []}
        return 1, {"verdict": "fail", "model_revision": rev, "reasons": ["latency"],
                   "transient": False}

    def deliver(self, robot, rev):
        self.delivers.append((robot["name"], rev))
        if robot["name"] == self.failing_robot:
            raise RuntimeError("ssh timeout")
        if robot["name"] in self.busy:
            return 75
        if self.hold.get(robot["name"]):  # push --unless-held, checked inside the lock
            return 76
        self.shadow[robot["name"]] = rev
        return 0


def _run(cfg, fakes, env=None):
    return watch.main(["--config", str(cfg)], list_commits=fakes.list_commits,
                      intake_fn=fakes.intake, deliver_fn=fakes.deliver,
                      observe_fn=fakes.observe, env=env or {})


def test_first_run_bootstraps_to_the_newest_commit(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C3, C2, C1])
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C3]
    commits = _state(tmp_path)["commits"]
    assert commits[C1]["intake"] == commits[C2]["intake"] == "skipped"
    assert commits[C1]["reason"] == "bootstrap"


def test_since_processes_only_later_commits(tmp_path):
    cfg = _config(tmp_path, since=C2, max_new_per_run=5)
    fakes = Fakes([C4, C3, C2, C1])
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C3, C4]
    assert _state(tmp_path)["commits"][C2]["reason"] == "since"


def test_since_not_found_exits_2(tmp_path):
    cfg = _config(tmp_path, since="9" * 40)
    assert _run(cfg, Fakes([C2, C1])) == 2


def test_pass_pushes_shadow_to_every_robot_and_records(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    rev = f"lane-seg-20260930-{C1[:8]}"
    assert fakes.delivers == [("pinky-a", rev), ("pinky-b", rev)]
    state = _state(tmp_path)
    rec = state["commits"][C1]
    assert rec["intake"] == "pass" and rec["model_revision"] == rev
    assert {n: r["status"] for n, r in rec["robots"].items()} == {"pinky-a": "ok", "pinky-b": "ok"}
    assert state["shadow"]["pinky-a"]["sha"] == C1


def test_same_commit_is_not_processed_twice(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C1] and len(fakes.delivers) == 2


def test_failed_robot_is_retried_later_without_intake(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1], failing_robot="pinky-a")
    assert _run(cfg, fakes) == 1
    assert [d[0] for d in fakes.delivers] == ["pinky-a", "pinky-b"]
    rec = _state(tmp_path)["commits"][C1]["robots"]
    assert rec["pinky-b"]["status"] == "ok"
    assert rec["pinky-a"]["status"] == "pending" and "ssh timeout" in rec["pinky-a"]["last_error"]
    fakes.failing_robot = None
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C1]  # intake ran once
    assert [d[0] for d in fakes.delivers] == ["pinky-a", "pinky-b", "pinky-a"]
    assert _state(tmp_path)["commits"][C1]["robots"]["pinky-a"]["status"] == "ok"


def test_robot_retries_are_bounded(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path, max_attempts=2)
    fakes = Fakes([C1], failing_robot="pinky-a")
    for _ in range(4):
        _run(cfg, fakes)
    assert [d[0] for d in fakes.delivers].count("pinky-a") == 2
    assert _state(tmp_path)["commits"][C1]["robots"]["pinky-a"]["status"] == "gave_up"


def test_newer_commit_supersedes_an_older_pending_robot(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1], failing_robot="pinky-a")
    assert _run(cfg, fakes) == 1
    fakes.commits, fakes.failing_robot = [C2, C1], None
    assert _run(cfg, fakes) == 0
    rev1, rev2 = (f"lane-seg-20260930-{c[:8]}" for c in (C1, C2))
    assert fakes.delivers[2:] == [("pinky-a", rev2), ("pinky-b", rev2)]
    assert ("pinky-a", rev1) not in fakes.delivers[2:]
    state = _state(tmp_path)
    assert state["commits"][C1]["robots"]["pinky-a"]["status"] == "superseded"
    assert state["shadow"]["pinky-a"]["sha"] == C2


def test_failed_intake_is_final_and_delivers_nothing(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1], verdict="fail")
    assert _run(cfg, fakes) == 0
    assert _run(cfg, fakes) == 0
    assert fakes.delivers == [] and fakes.intakes == [C1]
    rec = _state(tmp_path)["commits"][C1]
    assert rec["intake"] == "fail" and rec["reasons"] == ["latency"]


@pytest.mark.parametrize("kind", ["transient", "raise"])
def test_transient_intake_error_is_retried_up_to_max_attempts(tmp_path, kind):
    _seed(tmp_path, {})
    cfg = _config(tmp_path, max_attempts=3)
    fakes = Fakes([C1], intake_error=kind)
    assert _run(cfg, fakes) == 1
    rec = _state(tmp_path)["commits"][C1]
    assert rec["intake"] == "error" and rec["attempts"] == 1 and rec["last_error"]
    for _ in range(4):
        _run(cfg, fakes)
    assert fakes.intakes == [C1] * 3
    assert _state(tmp_path)["commits"][C1]["intake"] == "gave_up"
    fakes.intake_error = None  # a later success cannot happen: gave_up is final
    _run(cfg, fakes)
    assert fakes.intakes == [C1] * 3


def test_transient_then_pass(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1], intake_error="transient")
    assert _run(cfg, fakes) == 1
    fakes.intake_error = None
    assert _run(cfg, fakes) == 0
    rec = _state(tmp_path)["commits"][C1]
    assert rec["intake"] == "pass" and rec["attempts"] == 2


def test_at_most_n_intakes_per_run_oldest_first(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path, max_new_per_run=2)
    fakes = Fakes([C3, C2, C1])
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C1, C2]
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C1, C2, C3]


def test_hf_listing_failure_exits_3_and_keeps_state(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C1], list_error=OSError("offline"))
    assert _run(cfg, fakes) == 3
    assert not (tmp_path / "state.json").exists()
    assert fakes.intakes == []


def test_token_file_reaches_hf_listing(tmp_path):
    tok = tmp_path / "hf_token"
    tok.write_text("hf_secret", encoding="utf-8")
    cfg = _config(tmp_path)
    fakes = Fakes([])
    assert _run(cfg, fakes, env={"HF_TOKEN_FILE": str(tok), "HF_TOKEN": "hf_env"}) == 0
    assert _run(cfg, fakes, env={"HF_TOKEN": "hf_env"}) == 0
    assert fakes.listed == [("org/lane-seg", "hf_secret"), ("org/lane-seg", False)]


def test_save_state_is_atomic(tmp_path):
    path = tmp_path / "s" / "state.json"
    watch.save_state(path, {"version": 1, "repo": "org/m", "commits": {C1: {"intake": "pass"}}})
    assert watch.load_state(path, "org/m")["commits"][C1] == {"intake": "pass"}
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_load_state_refuses_other_repo(tmp_path):
    path = tmp_path / "state.json"
    watch.save_state(path, {"version": 1, "repo": "org/other", "commits": {}})
    with pytest.raises(ValueError, match="org/other"):
        watch.load_state(path, "org/m")


def test_default_deliverer_only_pushes_shadow_with_config_ssh(tmp_path, monkeypatch):
    seen = []
    fake = types.ModuleType("deliver")
    fake.main = lambda argv: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "deliver", fake)
    cfg = watch.load_config(_config(tmp_path, push_timeout_s=120))
    rc = watch.default_deliverer(cfg)({"name": "pinky-a", "host": "10.0.0.11"}, "rev-1")
    assert rc == 0
    argv = seen[0]
    assert argv[:3] == ["push", "10.0.0.11", "rev-1"]
    assert argv[argv.index("--identity") + 1] == "/etc/rosy/model-watch/id"
    assert argv[argv.index("--known-hosts") + 1] == "/etc/rosy/model-watch/kh"
    assert argv[argv.index("--models") + 1] == str(tmp_path / "models")
    assert argv[argv.index("--user") + 1] == "rosy"
    assert argv[argv.index("--timeout") + 1] == "120"
    assert argv[argv.index("--operator") + 1] == f"site:{watch.socket.gethostname()}"
    assert "--unless-held" in argv  # the site never overrides an operator's hold
    assert watch.load_config(_config(tmp_path))["push_timeout_s"] == 600


# --- the robot's real pointer and operator actions win (D-373 decision 7) -------------------

def rev_of(sha):
    return f"lane-seg-20260930-{sha[:8]}"


def test_delivery_decision():
    assert watch.delivery_decision("r2", {"shadow": None, "hold": None}) == "push"
    assert watch.delivery_decision("r2", {"shadow": "r1", "hold": None}) == "push"
    assert watch.delivery_decision("r2", {"shadow": "r2", "hold": None}) == "ok"
    assert watch.delivery_decision("r2", {"shadow": "r1", "hold": {"by": "ana"}}) == "held"


def test_manual_hold_stops_the_robot_until_release(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    fakes.hold["pinky-a"] = {"by": "ana", "action": "rollback"}
    assert _run(cfg, fakes) == 0
    assert fakes.delivers == [("pinky-b", rev_of(C1))]  # held robot not even tried
    assert _run(cfg, fakes) == 0
    rec = _state(tmp_path)["commits"][C1]["robots"]["pinky-a"]
    assert rec == {"status": "pending", "attempts": 0}  # a hold costs no attempt
    fakes.hold.pop("pinky-a")  # rosy_ml release-hold
    assert _run(cfg, fakes) == 0
    assert fakes.delivers[-1] == ("pinky-a", rev_of(C1))


def test_hold_set_between_observe_and_push_is_76_and_costs_nothing(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    real_observe = fakes.observe

    def racy(robot):  # the operator takes the hold right after the watcher looked
        got = real_observe(robot)
        fakes.hold[robot["name"]] = {"by": "ana"}
        return got

    fakes.observe = racy
    assert _run(cfg, fakes) == 0
    rec = _state(tmp_path)["commits"][C1]["robots"]
    assert rec["pinky-a"] == {"status": "pending", "attempts": 0}
    assert all(r != rev_of(C1) for r in fakes.shadow.values())


def test_busy_lock_is_retried_without_using_an_attempt(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path, max_attempts=1)
    fakes = Fakes([C1])
    fakes.busy.add("pinky-a")
    assert _run(cfg, fakes) == 0
    assert _state(tmp_path)["commits"][C1]["robots"]["pinky-a"] == {"status": "pending",
                                                                    "attempts": 0}
    fakes.busy.clear()
    assert _run(cfg, fakes) == 0
    assert fakes.shadow["pinky-a"] == rev_of(C1)


def test_after_release_a_robot_behind_is_brought_back_to_the_newest(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    fakes.commits = [C2, C1]
    assert _run(cfg, fakes) == 0
    assert fakes.shadow["pinky-a"] == rev_of(C2)
    # an operator rolls pinky-a back to C1 (hold), later releases the hold
    fakes.shadow["pinky-a"], fakes.hold["pinky-a"] = rev_of(C1), {"by": "ana"}
    n = len(fakes.delivers)
    assert _run(cfg, fakes) == 0
    assert len(fakes.delivers) == n
    fakes.hold.pop("pinky-a")
    assert _run(cfg, fakes) == 0
    assert fakes.delivers[-1] == ("pinky-a", rev_of(C2))
    assert fakes.shadow["pinky-a"] == rev_of(C2)
    assert _state(tmp_path)["commits"][C2]["robots"]["pinky-a"]["status"] == "ok"


def test_unreachable_robot_that_is_up_to_date_is_not_an_error(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0

    def offline(robot):
        raise RuntimeError("no route")

    fakes.observe = offline
    assert _run(cfg, fakes) == 0
    assert _state(tmp_path)["commits"][C1]["robots"]["pinky-a"]["status"] == "ok"


def test_model_already_on_the_robot_is_not_pushed_again(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    fakes.shadow["pinky-a"] = rev_of(C1)  # an operator got there first
    assert _run(cfg, fakes) == 0
    assert fakes.delivers == [("pinky-b", rev_of(C1))]
    assert _state(tmp_path)["commits"][C1]["robots"]["pinky-a"]["status"] == "ok"


def test_unreadable_robot_is_a_failed_attempt(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])

    def offline(robot):
        if robot["name"] == "pinky-a":
            raise RuntimeError("cannot read the shadow pointer")
        return {"shadow": None, "history": []}

    fakes.observe = offline
    assert _run(cfg, fakes) == 1
    rec = _state(tmp_path)["commits"][C1]["robots"]
    assert rec["pinky-a"]["status"] == "pending" and rec["pinky-a"]["attempts"] == 1
    assert rec["pinky-b"]["status"] == "ok"


def test_robot_added_later_gets_the_newest_passed_commit(tmp_path):
    _seed(tmp_path, {})
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    fakes.commits = [C2, C1]
    assert _run(cfg, fakes) == 0
    cfg = _config(tmp_path, robots=[{"name": "pinky-a", "host": "10.0.0.11"},
                                    {"name": "pinky-b", "host": "10.0.0.12"},
                                    {"name": "pinky-c", "host": "10.0.0.13"}])
    assert _run(cfg, fakes) == 0
    assert [d for d in fakes.delivers if d[0] == "pinky-c"] == [("pinky-c", rev_of(C2))]
    assert "pinky-c" not in _state(tmp_path)["commits"][C1]["robots"]


def test_ensure_targets_is_pure_and_newest_only():
    state = {"commits": {C1: _passed(1, {"pinky-a": ("ok", 1)}),
                         C2: _passed(2, {"pinky-a": ("ok", 1)}),
                         C3: {"order": 3, "intake": "fail"}}}
    new = watch.ensure_targets(state, ["pinky-a", "pinky-c"])
    assert new["commits"][C2]["robots"]["pinky-c"] == {"status": "pending", "attempts": 0}
    assert "pinky-c" not in new["commits"][C1]["robots"]
    assert "pinky-c" not in state["commits"][C2]["robots"]
