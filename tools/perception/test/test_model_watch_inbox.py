"""D-373 decision 8: the site watcher's default backend is the store inbox (no HF at all)."""
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "tools" / "perception", ROOT / "tools" / "perception" / "model"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import store  # noqa: E402
import watch  # noqa: E402


def _config(tmp_path, **extra):
    doc = {
        "store": str(tmp_path / "store"),
        "robots": [{"name": "pinky-a", "host": "10.0.0.11"},
                   {"name": "pinky-b", "host": "10.0.0.12"}],
        "ssh": {"identity": "/etc/rosy/model-watch/id", "known_hosts": "/etc/rosy/model-watch/kh"},
        "intake_out": str(tmp_path / "models"),
        "state_file": str(tmp_path / "state.json"),
        "max_new_per_run": 2,
        **extra,
    }
    path = tmp_path / "model-watch.yaml"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _drop(tmp_path, name, *, ready=True, mtime=None, payload=None):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    folder = st.inbox / name
    folder.mkdir()
    (folder / "model.onnx").write_text(payload or name)
    if ready:
        (folder / store.READY).write_text(store.content_sha(folder))
        if mtime:
            os.utime(folder / store.READY, (mtime, mtime))
    return folder


def _state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


def rev_of(name):
    return f"rev-{name}"


class Fakes:
    def __init__(self, verdict="pass"):
        self.verdict = verdict
        self.intakes, self.delivers, self.shadow = [], [], {}

    def intake(self, name):
        self.intakes.append(name)
        if self.verdict == "transient":
            return 1, {"verdict": "fail", "model_revision": None, "transient": True,
                       "reasons": ["OSError: disk full"]}
        if self.verdict == "pass":
            return 0, {"verdict": "pass", "model_revision": rev_of(name), "reasons": []}
        return 1, {"verdict": "fail", "model_revision": rev_of(name),
                   "reasons": ["latency p50 900 ms > 400 ms"], "transient": False}

    def observe(self, robot):
        return {"shadow": self.shadow.get(robot["name"]), "hold": None}

    def deliver(self, robot, rev):
        self.delivers.append((robot["name"], rev))
        self.shadow[robot["name"]] = rev
        return 0


def _run(cfg, fakes, env=None):
    def no_hf(*a):
        raise AssertionError("the inbox backend never lists HF")
    return watch.main(["--config", str(cfg)], list_commits=no_hf, intake_fn=fakes.intake,
                      deliver_fn=fakes.deliver, observe_fn=fakes.observe, env=env or {})


# --- config ---------------------------------------------------------------------------------

def test_inbox_is_the_default_backend_and_needs_only_a_store(tmp_path):
    cfg = watch.load_config(_config(tmp_path))
    assert cfg["backend"] == "inbox" and "repo" not in cfg


@pytest.mark.parametrize("change", [
    {"store": None},
    {"store": ""},
    {"backend": "s3"},
    {"since": "1" * 40},              # since is an HF commit notion
    {"backend": "hf"},                # hf needs repo
])
def test_bad_inbox_config_exits_2(tmp_path, change):
    doc_path = _config(tmp_path, **change)
    doc = json.loads(doc_path.read_text())
    doc = {k: v for k, v in doc.items() if v is not None}
    doc_path.write_text(json.dumps(doc))
    assert _run(doc_path, Fakes()) == 2


def test_missing_store_is_a_listing_failure_not_an_empty_inbox(tmp_path):
    rc = _run(_config(tmp_path), Fakes())
    assert rc == watch.LIST_FAILED_EXIT
    assert not (tmp_path / "state.json").exists()


# --- one run --------------------------------------------------------------------------------

def test_ready_folder_passes_is_accepted_and_delivered(tmp_path):
    _drop(tmp_path, "m1")
    _drop(tmp_path, "half", ready=False)      # still syncing: not touched
    fakes = Fakes()
    assert _run(_config(tmp_path), fakes) == 0
    assert fakes.intakes == ["m1"]
    assert fakes.delivers == [("pinky-a", "rev-m1"), ("pinky-b", "rev-m1")]
    st = store.Store(tmp_path / "store")
    assert (st.accepted / "rev-m1" / "model.onnx").is_file()
    assert sorted(p.name for p in st.inbox.iterdir()) == ["half"]
    rec = _state(tmp_path)["commits"]["m1"]
    assert rec["intake"] == "pass" and rec["model_revision"] == "rev-m1"
    assert rec["content_sha"] == store.content_sha(st.accepted / "rev-m1")
    assert _state(tmp_path)["repo"] == "store-inbox"


def test_same_folder_is_not_processed_twice(tmp_path):
    _drop(tmp_path, "m1")
    fakes = Fakes()
    cfg = _config(tmp_path)
    assert _run(cfg, fakes) == 0 and _run(cfg, fakes) == 0
    assert fakes.intakes == ["m1"] and len(fakes.delivers) == 2


def test_failed_intake_is_rejected_with_the_reason(tmp_path):
    _drop(tmp_path, "bad")
    fakes = Fakes(verdict="fail")
    assert _run(_config(tmp_path), fakes) == 0
    st = store.Store(tmp_path / "store")
    reason = (st.rejected / "bad" / store.REASON).read_text(encoding="utf-8")
    assert "latency p50" in reason
    assert fakes.delivers == [] and not list(st.inbox.iterdir())


def test_transient_error_stays_in_the_inbox_and_is_bounded(tmp_path):
    _drop(tmp_path, "m1")
    fakes = Fakes(verdict="transient")
    cfg = _config(tmp_path, max_attempts=2)
    assert _run(cfg, fakes) == 1
    st = store.Store(tmp_path / "store")
    assert st.list_inbox() == ["m1"]
    assert _state(tmp_path)["commits"]["m1"]["intake"] == "error"
    assert _run(cfg, fakes) == 0          # second attempt: gave_up (not a retry any more)
    assert _state(tmp_path)["commits"]["m1"]["intake"] == "gave_up"
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == ["m1", "m1"]
    assert st.list_inbox() == ["m1"]      # an infrastructure error is not the model's fault


def test_transient_then_pass(tmp_path):
    _drop(tmp_path, "m1")
    fakes = Fakes(verdict="transient")
    cfg = _config(tmp_path)
    assert _run(cfg, fakes) == 1
    fakes.verdict = "pass"
    assert _run(cfg, fakes) == 0
    assert _state(tmp_path)["commits"]["m1"]["attempts"] == 2
    assert fakes.delivers[-1] == ("pinky-b", "rev-m1")


def test_oldest_marker_first_bounded_per_run_newest_wins(tmp_path):
    _drop(tmp_path, "c", mtime=3000)
    _drop(tmp_path, "a", mtime=1000)
    _drop(tmp_path, "b", mtime=2000)
    fakes = Fakes()
    cfg = _config(tmp_path, max_new_per_run=2)
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == ["a", "b"]
    assert fakes.delivers == [("pinky-a", "rev-b"), ("pinky-b", "rev-b")]  # newest passed only
    assert _run(cfg, fakes) == 0
    assert fakes.intakes == ["a", "b", "c"]
    assert fakes.shadow == {"pinky-a": "rev-c", "pinky-b": "rev-c"}


def test_a_folder_left_behind_after_a_verdict_is_moved_on_the_next_run(tmp_path, monkeypatch):
    _drop(tmp_path, "m1")
    fakes = Fakes()
    cfg = _config(tmp_path)

    def broken(self, folder, revision):
        raise OSError("NAS went away")
    monkeypatch.setattr(store.Store, "accept", broken)
    assert _run(cfg, fakes) == 1           # the move failed: retried, not re-intaken
    assert fakes.delivers                  # the model itself passed and is delivered
    monkeypatch.undo()
    assert _run(cfg, fakes) == 0
    st = store.Store(tmp_path / "store")
    assert (st.accepted / "rev-m1").is_dir() and not (st.inbox / "m1").exists()
    assert fakes.intakes == ["m1"]


def test_a_reused_folder_name_with_new_content_is_rejected(tmp_path):
    cfg = _config(tmp_path)
    fakes = Fakes()
    _drop(tmp_path, "m1")
    assert _run(cfg, fakes) == 0
    _drop(tmp_path, "m1", payload="other weights")
    assert _run(cfg, fakes) == 0
    st = store.Store(tmp_path / "store")
    assert "reused" in (st.rejected / "m1" / store.REASON).read_text(encoding="utf-8")
    assert fakes.intakes == ["m1"]


def test_default_inbox_intake_uses_the_store_ref(tmp_path, monkeypatch):
    got = {}
    fake = types.ModuleType("intake")
    fake.DEFAULT_GATE, fake.ROOT = "gate.yaml", "/repo"

    def run(source, **kw):
        got.update(kw, source=source)
        return 1, {"verdict": "fail"}
    fake.run = run
    monkeypatch.setitem(sys.modules, "intake", fake)
    cfg = watch.load_config(_config(tmp_path))
    watch.default_inbox_intake(cfg)("m1")
    assert got["source"] == "store-inbox:m1" and got["store"] == str(tmp_path / "store")
    assert "downloader" not in got or got["downloader"] is None


def test_the_inbox_backend_never_reads_an_hf_token(tmp_path, monkeypatch):
    _drop(tmp_path, "m1")
    monkeypatch.setattr(watch, "read_hf_token", lambda *a: pytest.fail("token read"))
    assert _run(_config(tmp_path), Fakes(), env={"HF_TOKEN_FILE": "/nope"}) == 0


def test_a_missing_package_stops_the_run_as_a_config_error_and_spends_no_attempt(tmp_path, capsys):
    """Review 2026-10-01: a missing `onnx` in the site venv was retried as transient
    until gave_up, so auto-delivery stopped without a word. It is a config error."""
    cfg = _config(tmp_path)
    _drop(tmp_path, "m1")
    fakes = Fakes()

    def intake(name):
        fakes.intakes.append(name)
        return 4, {"verdict": "fail", "model_revision": None, "transient": False,
                   "config_error": True, "reasons": ["ImportError: No module named 'onnx'"]}
    fakes.intake = intake
    for _ in range(watch_max := 3):
        assert _run(cfg, fakes) == watch.CONFIG_EXIT
    assert watch.CONFIG_EXIT == 6
    assert fakes.intakes == ["m1"] * watch_max        # tried again every run, never given up
    assert "m1" not in _state(tmp_path).get("commits", {})
    assert (tmp_path / "store" / "models" / "inbox" / "m1").is_dir()
    assert "onnx" in capsys.readouterr().err
