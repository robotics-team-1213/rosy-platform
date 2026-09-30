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

C1, C2, C3 = "1" * 40, "2" * 40, "3" * 40


def _config(tmp_path, **extra):
    doc = {
        "repo": "org/lane-seg",
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


# --- pure core ------------------------------------------------------------------------------

def test_plan_run_takes_unseen_commits_oldest_first():
    state = {"commits": {C2: {"intake": "pass"}}}
    assert watch.plan_run([C3, C2, C1], state, limit=5) == [C1, C3]
    assert watch.plan_run([C3, C2, C1], state, limit=1) == [C1]
    assert watch.plan_run([C3, C2, C1], {"commits": {}}, limit=0) == []
    assert watch.plan_run([], {}, limit=3) == []


def test_apply_result_is_pure_and_records():
    state = {"version": 1, "repo": "org/m", "commits": {}}
    new = watch.apply_result(state, C1, {"intake": "fail", "reasons": ["x"]})
    assert state["commits"] == {}
    assert new["commits"][C1] == {"intake": "fail", "reasons": ["x"]}
    assert new["repo"] == "org/m"


def test_hf_token_from_file_then_env_never_argv(tmp_path):
    tok = tmp_path / "hf_token"
    tok.write_text("hf_file\n", encoding="utf-8")
    assert watch.read_hf_token({"HF_TOKEN_FILE": str(tok), "HF_TOKEN": "hf_env"}) == "hf_file"
    assert watch.read_hf_token({"HF_TOKEN": "hf_env"}) == "hf_env"
    assert watch.read_hf_token({}) is None
    with pytest.raises(OSError):
        watch.read_hf_token({"HF_TOKEN_FILE": str(tmp_path / "missing")})
    with pytest.raises(SystemExit):  # there is no --token option
        watch.main(["--config", "x", "--token", "hf_x"])


def test_save_state_is_atomic(tmp_path):
    path = tmp_path / "s" / "state.json"
    watch.save_state(path, {"version": 1, "commits": {C1: {"intake": "pass"}}})
    assert watch.load_state(path, "org/m")["commits"][C1] == {"intake": "pass"}
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_load_state_refuses_other_repo(tmp_path):
    path = tmp_path / "state.json"
    watch.save_state(path, {"version": 1, "repo": "org/other", "commits": {}})
    with pytest.raises(ValueError, match="org/other"):
        watch.load_state(path, "org/m")
    assert watch.load_state(tmp_path / "none.json", "org/m") == {
        "version": 1, "repo": "org/m", "commits": {}}


@pytest.mark.parametrize("change", [
    {"repo": "not-a-repo"},
    {"robots": []},
    {"robots": [{"name": "a b", "host": "h"}]},
    {"robots": [{"name": "a", "host": "h"}, {"name": "a", "host": "h2"}]},
    {"ssh": {"identity": "/k"}},
    {"max_new_per_run": 0},
])
def test_bad_config_exits_2(tmp_path, change):
    cfg = _config(tmp_path, **change)
    assert watch.main(["--config", str(cfg)], list_commits=lambda *a: [C1],
                      intake_fn=None, deliver_fn=None, env={}) == 2


# --- one run, HF / intake / deliver injected -----------------------------------------------

class Fakes:
    def __init__(self, commits, verdict="pass", failing_robot=None, list_error=None):
        self.commits, self.verdict = commits, verdict
        self.failing_robot, self.list_error = failing_robot, list_error
        self.listed, self.intakes, self.delivers = [], [], []

    def list_commits(self, repo, token):
        self.listed.append((repo, token))
        if self.list_error:
            raise self.list_error
        return list(self.commits)

    def intake(self, sha):
        self.intakes.append(sha)
        rev = f"lane-seg-20260930-{sha[:8]}"
        if self.verdict == "pass":
            return 0, {"verdict": "pass", "model_revision": rev, "reasons": []}
        return 1, {"verdict": "fail", "model_revision": rev, "reasons": ["latency"]}

    def deliver(self, robot, rev):
        self.delivers.append((robot["name"], rev))
        if robot["name"] == self.failing_robot:
            raise RuntimeError("ssh timeout")
        return 0


def _run(cfg, fakes, env=None):
    return watch.main(["--config", str(cfg)], list_commits=fakes.list_commits,
                      intake_fn=fakes.intake, deliver_fn=fakes.deliver, env=env or {})


def test_pass_pushes_shadow_to_every_robot_and_records(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    rev = f"lane-seg-20260930-{C1[:8]}"
    assert fakes.delivers == [("pinky-a", rev), ("pinky-b", rev)]
    rec = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["commits"][C1]
    assert rec["intake"] == "pass" and rec["model_revision"] == rev
    assert rec["robots"] == {"pinky-a": "ok", "pinky-b": "ok"}


def test_same_commit_is_not_processed_twice(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C1])
    assert _run(cfg, fakes) == 0
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == [C1] and len(fakes.delivers) == 2


def test_robot_failure_does_not_block_others(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C1], failing_robot="pinky-a")
    assert _run(cfg, fakes) == 1
    assert [d[0] for d in fakes.delivers] == ["pinky-a", "pinky-b"]
    rec = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["commits"][C1]
    assert rec["robots"]["pinky-b"] == "ok"
    assert rec["robots"]["pinky-a"].startswith("failed") and "ssh timeout" in rec["robots"]["pinky-a"]


def test_failed_intake_records_reason_and_delivers_nothing(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes([C1], verdict="fail")
    assert _run(cfg, fakes) == 0
    assert fakes.delivers == []
    rec = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["commits"][C1]
    assert rec["intake"] == "fail" and rec["reasons"] == ["latency"]


def test_at_most_n_per_run_oldest_first(tmp_path):
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
    assert _run(cfg, fakes, env={"HF_TOKEN_FILE": str(tok)}) == 0
    assert fakes.listed == [("org/lane-seg", "hf_secret")]


def test_default_deliverer_only_pushes_shadow_with_config_ssh(tmp_path, monkeypatch):
    seen = []
    fake = types.ModuleType("deliver")
    fake.main = lambda argv: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "deliver", fake)
    cfg = watch.load_config(_config(tmp_path))
    rc = watch.default_deliverer(cfg)({"name": "pinky-a", "host": "10.0.0.11"}, "rev-1")
    assert rc == 0
    argv = seen[0]
    assert argv[:3] == ["push", "10.0.0.11", "rev-1"]
    assert argv[argv.index("--identity") + 1] == "/etc/rosy/model-watch/id"
    assert argv[argv.index("--known-hosts") + 1] == "/etc/rosy/model-watch/kh"
    assert argv[argv.index("--models") + 1] == str(tmp_path / "models")
    assert argv[argv.index("--user") + 1] == "rosy"
