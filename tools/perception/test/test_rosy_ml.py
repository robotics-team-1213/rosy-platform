"""D-373 decision 7: the one operator CLI, rosy_ml."""
import json
import os
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "tools" / "perception") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "perception"))

import rosy_ml  # noqa: E402


def _init(tmp_path, *extra, env_config=True, monkeypatch=None):
    cfg = tmp_path / "ml.yaml"
    if monkeypatch:
        monkeypatch.setenv("ROSY_ML_CONFIG", str(cfg))
    key = tmp_path / "id"
    key.write_text("k")
    if os.name != "nt":
        key.chmod(0o600)
    kh = tmp_path / "kh"
    kh.write_text("")
    argv = ["init", "--operator", "ana", "--robot", "pinky-a=10.0.0.11",
            "--robot", "pinky-b=pinky-b.local", "--identity", str(key),
            "--known-hosts", str(kh), "--intake-out", str(tmp_path / "models"), *extra]
    return cfg, rosy_ml.main(argv)


# --- config -------------------------------------------------------------------------------

def test_config_path_per_os():
    assert rosy_ml.config_path({"ROSY_ML_CONFIG": "/x/ml.yaml"}, "linux") == Path("/x/ml.yaml")
    assert rosy_ml.config_path({"APPDATA": r"C:\U\AppData\Roaming"}, "win32") == \
        Path(r"C:\U\AppData\Roaming") / "Rosy" / "ml.yaml"
    assert rosy_ml.config_path({"HOME": "/home/ana"}, "linux") == \
        Path("/home/ana/.config/rosy/ml.yaml")
    assert rosy_ml.config_path({"HOME": "/h", "XDG_CONFIG_HOME": "/c"}, "linux") == \
        Path("/c/rosy/ml.yaml")


def test_init_writes_paths_only_and_refuses_overwrite(tmp_path, monkeypatch):
    cfg, rc = _init(tmp_path, "--hf-repo", "org/lane-seg",
                    "--hf-token-file", str(tmp_path / "hf"), monkeypatch=monkeypatch)
    assert rc == 0
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert doc["operator"] == "ana"
    assert doc["robots"] == {"pinky-a": "10.0.0.11", "pinky-b": "pinky-b.local"}
    assert doc["hf_repo"] == "org/lane-seg" and doc["hf_token_file"] == str(tmp_path / "hf")
    assert not [k for k in doc if "token" in k and not k.endswith("_file")]
    _, rc = _init(tmp_path, monkeypatch=monkeypatch)
    assert rc == 2  # exists
    _, rc = _init(tmp_path, "--force", monkeypatch=monkeypatch)
    assert rc == 0


def test_init_operator_defaults_to_os_user(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "ml.yaml"))
    monkeypatch.setattr(rosy_ml.getpass, "getuser", lambda: "osuser")
    rc = rosy_ml.main(["init", "--robot", "a=h", "--identity", "/k", "--known-hosts", "/kh"])
    assert rc == 0
    assert yaml.safe_load((tmp_path / "ml.yaml").read_text())["operator"] == "osuser"


@pytest.mark.parametrize("bad", [["--robot", "a b=h"], ["--robot", "a=-oProxy"], ["--robot", "a"]])
def test_init_rejects_unsafe_robots(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "ml.yaml"))
    assert rosy_ml.main(["init", *bad, "--identity", "/k", "--known-hosts", "/kh"]) == 2
    assert not (tmp_path / "ml.yaml").exists()


def test_load_config_refuses_inline_secrets(tmp_path):
    p = tmp_path / "ml.yaml"
    p.write_text(yaml.safe_dump({"operator": "a", "robots": {"a": "h"},
                                 "ssh": {"identity": "/k", "known_hosts": "/kh"},
                                 "hf_token": "hf_xxx"}))
    with pytest.raises(ValueError, match="hf_token"):
        rosy_ml.load_config(p)


def test_config_from_watch():
    watch_cfg = {"backend": "hf", "repo": "org/m", "robots": [{"name": "a", "host": "h"}],
                 "ssh": {"identity": "/k", "known_hosts": "/kh"}, "intake_out": "/o",
                 "replay_root": "/r"}
    cfg = rosy_ml.config_from_watch(watch_cfg, hostname="fleet-1")
    assert cfg["operator"] == "site:fleet-1" and cfg["robots"] == {"a": "h"}
    assert cfg["hf_repo"] == "org/m" and cfg["hf_token_file"] == "/etc/rosy/site/secrets/hf_token"
    assert cfg["replay_root"] == "/r"


# --- wrappers: names -> hosts, config SSH, existing module functions -----------------------

def test_deliver_rollback_status_resolve_names(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch=monkeypatch)
    seen = []
    fake = types.ModuleType("deliver")
    fake.main = lambda argv, runner=None: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "deliver", fake)
    assert rosy_ml.main(["deliver", "pinky-a", "rev-1"]) == 0
    assert rosy_ml.main(["rollback", "pinky-b"]) == 0
    assert rosy_ml.main(["release-hold", "pinky-b"]) == 0
    assert rosy_ml.main(["status"]) == 0
    push, rollback, release, *status = seen
    assert push[:3] == ["push", "10.0.0.11", "rev-1"]
    assert push[push.index("--operator") + 1] == "ana"
    assert push[push.index("--models") + 1] == str(tmp_path / "models")
    assert push[push.index("--identity") + 1] == str(tmp_path / "id")
    assert rollback[:2] == ["rollback", "pinky-b.local"] and "--operator" in rollback
    assert release[:2] == ["release-hold", "pinky-b.local"]
    assert [s[:2] for s in status] == [["status", "10.0.0.11"], ["status", "pinky-b.local"]]
    assert rosy_ml.main(["deliver", "nobody", "rev-1"]) == 2


def test_harvest_uses_core_token_file(tmp_path, monkeypatch):
    _init(tmp_path, "--core-token-file", str(tmp_path / "core.token"), monkeypatch=monkeypatch)
    seen = []
    fake = types.ModuleType("harvest")
    fake.main = lambda argv: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "harvest", fake)
    assert rosy_ml.main(["harvest", "pinky-a", "--dest", str(tmp_path / "raw")]) == 0
    argv = seen[0]
    assert argv[0] == "10.0.0.11"
    assert argv[argv.index("--core-token-file") + 1] == str(tmp_path / "core.token")
    assert argv[argv.index("--dest") + 1] == str(tmp_path / "raw")
    assert "--assume-idle" not in argv
    assert rosy_ml.main(["harvest", "pinky-a", "--assume-idle"]) == 0
    assert "--assume-idle" in seen[1]


def test_intake_passes_the_token_file(tmp_path, monkeypatch):
    tok = tmp_path / "hf"
    tok.write_text("hf_secret")
    _init(tmp_path, "--hf-repo", "org/m", "--hf-token-file", str(tok), monkeypatch=monkeypatch)
    got = {}
    fake = types.ModuleType("intake")
    fake.DEFAULT_GATE, fake.ROOT = "g", "/repo"

    def run(source, **kw):
        got.update(kw, source=source)
        kw["downloader"](repo_id="org/m", revision="a" * 40, local_dir="d")
        return 0, {"verdict": "pass"}

    fake.run = run
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = lambda **kw: got.update(download=kw)
    monkeypatch.setitem(sys.modules, "intake", fake)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    assert rosy_ml.main(["intake", f"hf:org/m@{'a' * 40}"]) == 0
    assert got["out"] == str(tmp_path / "models")
    assert got["download"]["token"] == "hf_secret"


# --- doctor ---------------------------------------------------------------------------------

class Robot:
    """Fake ssh / ssh-keygen / TCP for one robot."""

    def __init__(self, **broken):
        self.broken = broken

    def runner(self, cmd, **kw):
        text = " ".join(cmd)
        ok, out = True, ""
        if cmd[0] == "ssh-keygen":
            ok = not self.broken.get("known_hosts")
            out = f"{cmd[2]} ssh-ed25519 AAAA" if ok else ""
        elif "cat /var/lib/rosy/models/hold" in text:
            out = self.broken.get("hold", "")
        elif "sudo -n stat" in text:
            out = self.broken.get("models", "root:rosy-camera 750") + "\n"
        elif "import onnxruntime" in text:
            ok = not self.broken.get("remote_ort")
        elif "sudo -n true" in text:
            ok = not self.broken.get("sudo")
        elif cmd[-1] == "true":
            ok = not self.broken.get("ssh")
        return types.SimpleNamespace(returncode=0 if ok else 1, stdout=out, stderr="")

    def connect(self, addr, timeout):
        assert timeout == 3 and addr[1] == 22
        if self.broken.get("tcp"):
            raise OSError("timed out")
        return types.SimpleNamespace(close=lambda: None)


def _doctor(tmp_path, monkeypatch, robot, *extra_init, local_ort=True, clips=1):
    _init(tmp_path, *extra_init, monkeypatch=monkeypatch)
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: clips)
    return rosy_ml.main(["doctor", "pinky-a"], runner=robot.runner, connect=robot.connect,
                        find_spec=lambda name: object() if local_ort else None)


def test_doctor_all_green(tmp_path, monkeypatch, capsys):
    assert _doctor(tmp_path, monkeypatch, Robot()) == 0
    out = capsys.readouterr().out
    assert "✗" not in out and out.count("✓") >= 8


@pytest.mark.parametrize("broken, words", [
    ({"known_hosts": True}, "known_hosts"),
    ({"ssh": True}, "authorized_keys"),
    ({"sudo": True}, "sudo"),
    ({"models": "root:root 755"}, "install-learned-perception"),
    ({"remote_ort": True}, "onnxruntime"),
])
def test_doctor_names_the_fix(tmp_path, monkeypatch, capsys, broken, words):
    assert _doctor(tmp_path, monkeypatch, Robot(**broken)) == 1
    bad = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("✗")]
    assert bad and words in bad[0]


def test_doctor_unreachable_skips_remote_checks(tmp_path, monkeypatch, capsys):
    assert _doctor(tmp_path, monkeypatch, Robot(tcp=True)) == 1
    out = capsys.readouterr().out
    assert "TCP 22" in out and "skipped" in out


def test_doctor_hf_token_and_replay_required_with_a_repo(tmp_path, monkeypatch, capsys):
    rc = _doctor(tmp_path, monkeypatch, Robot(), "--hf-repo", "org/m",
                 "--hf-token-file", str(tmp_path / "missing"), clips=0)
    assert rc == 1
    out = capsys.readouterr().out
    assert "HF token" in out and "replay" in out


def test_doctor_local_onnxruntime_is_advisory(tmp_path, monkeypatch, capsys):
    assert _doctor(tmp_path, monkeypatch, Robot(), local_ort=False) == 0
    assert "onnxruntime" in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="POSIX key modes")
def test_doctor_flags_an_open_key(tmp_path, monkeypatch, capsys):
    _init(tmp_path, monkeypatch=monkeypatch)
    (tmp_path / "id").chmod(0o644)
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    r = Robot()
    assert rosy_ml.main(["doctor", "pinky-a"], runner=r.runner, connect=r.connect,
                        find_spec=lambda n: object()) == 1
    assert "chmod 600" in capsys.readouterr().out


def test_doctor_without_config_says_run_init(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "none.yaml"))
    assert rosy_ml.main(["doctor"]) == 1
    assert "rosy_ml init" in capsys.readouterr().out


def test_doctor_watch_config(tmp_path, monkeypatch, capsys):
    key = tmp_path / "id"
    key.write_text("k")
    if os.name != "nt":
        key.chmod(0o600)
    wc = tmp_path / "model-watch.yaml"
    wc.write_text(json.dumps({"backend": "hf", "repo": "org/m",
                              "robots": [{"name": "pinky-a", "host": "h"}],
                              "ssh": {"identity": str(key), "known_hosts": str(tmp_path / "kh")},
                              "intake_out": str(tmp_path), "state_file": str(tmp_path / "s"),
                              "hf_token_file": str(key)}))
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    r = Robot()
    assert rosy_ml.main(["doctor", "--watch-config", str(wc)], runner=r.runner,
                        connect=r.connect, find_spec=lambda n: object(),
                        resolve=lambda h, p: []) == 0
    assert "site:" in capsys.readouterr().out


# --- review: recursive secret check, doctor robustness, holds ------------------------------

def test_inline_secret_check_is_recursive(tmp_path):
    p = tmp_path / "ml.yaml"
    p.write_text(yaml.safe_dump({"operator": "a", "robots": {"a": "h"},
                                 "ssh": {"identity": "/k", "known_hosts": "/kh",
                                         "extra": [{"hf_token": "hf_x"}]}}))
    with pytest.raises(ValueError, match="hf_token"):
        rosy_ml.load_config(p)


def test_doctor_turns_any_check_exception_into_a_cross(tmp_path, monkeypatch, capsys):
    robot = Robot()

    def flaky(cmd, **kw):
        if "sudo -n true" in " ".join(cmd):
            raise ValueError("weird")
        return robot.runner(cmd, **kw)

    _init(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    rc = rosy_ml.main(["doctor", "pinky-a"], runner=flaky, connect=robot.connect,
                      find_spec=lambda n: object())
    assert rc == 1
    bad = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("✗")]
    assert len(bad) == 1 and "sudo" in bad[0] and "ValueError" in bad[0]


def test_doctor_shows_a_hold_as_advisory(tmp_path, monkeypatch, capsys):
    hold = json.dumps({"by": "ana", "action": "rollback", "revision": "r1"})
    assert _doctor(tmp_path, monkeypatch, Robot(hold=hold)) == 0
    out = capsys.readouterr().out
    assert "! pinky-a: held by ana" in out and "rosy_ml release-hold pinky-a" in out


def test_doctor_flags_a_hold_older_than_a_day(tmp_path, monkeypatch, capsys):
    hold = json.dumps({"by": "ana", "ts": "2026-09-01T08:00:00Z", "action": "rollback"})
    monkeypatch.setattr(rosy_ml, "_utcnow", lambda: rosy_ml.dt.datetime(
        2026, 9, 2, 14, 0, tzinfo=rosy_ml.dt.timezone.utc))
    assert _doctor(tmp_path, monkeypatch, Robot(hold=hold)) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "held by ana" in ln][0]
    assert line.startswith("!") and "30 h" in line and "older than 24 h" in line


def test_doctor_recent_hold_shows_age_without_the_warning(tmp_path, monkeypatch, capsys):
    hold = json.dumps({"by": "ana", "ts": "2026-09-02T12:00:00Z"})
    monkeypatch.setattr(rosy_ml, "_utcnow", lambda: rosy_ml.dt.datetime(
        2026, 9, 2, 14, 0, tzinfo=rosy_ml.dt.timezone.utc))
    assert _doctor(tmp_path, monkeypatch, Robot(hold=hold)) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "held by ana" in ln][0]
    assert "2 h" in line and "older than" not in line


def test_robot_names_are_positional(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch=monkeypatch)
    seen = []
    fake = types.ModuleType("deliver")
    fake.main = lambda argv, runner=None: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "deliver", fake)
    assert rosy_ml.main(["release-hold", "pinky-a"]) == 0
    assert seen[0][:2] == ["release-hold", "10.0.0.11"]


# --- store (D-373 decision 8) ---------------------------------------------------------------

def _store_with(tmp_path):
    import store
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    src = tmp_path / "ds"
    src.mkdir()
    (src / "manifest.json").write_text("{}")
    _, sha = st.put_dataset(src, "lane")
    ready = st.inbox / "m1"
    ready.mkdir()
    (ready / "model.onnx").write_text("w")
    (ready / "READY").write_text(store.content_sha(ready))
    (st.inbox / "half").mkdir()
    return st, sha


def test_init_records_the_store_path(tmp_path, monkeypatch):
    cfg, rc = _init(tmp_path, "--store", str(tmp_path / "store"), monkeypatch=monkeypatch)
    assert rc == 0
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["store"] == str(tmp_path / "store")


def test_config_from_an_inbox_watch_config_has_the_store_and_no_hf():
    cfg = rosy_ml.config_from_watch({"store": "/srv/rosy/store", "backend": "inbox",
                                     "robots": [{"name": "a", "host": "h"}],
                                     "ssh": {"identity": "/k", "known_hosts": "/kh"},
                                     "intake_out": "/o"}, hostname="site")
    assert cfg["store"] == "/srv/rosy/store"
    assert "hf_repo" not in cfg and "hf_token_file" not in cfg


def test_doctor_checks_the_store(tmp_path, monkeypatch, capsys):
    _store_with(tmp_path)
    assert _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "store")) == 0
    out = capsys.readouterr().out
    assert "✓ store" in out and "1 ready in the inbox" in out
    assert "HF" not in out  # no HF anywhere without hf_repo


def test_doctor_missing_store_is_a_cross_with_a_fix(tmp_path, monkeypatch, capsys):
    rc = _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "nowhere"))
    assert rc == 1
    bad = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("✗")]
    assert bad and "store" in bad[0] and "mount" in bad[0]


def test_doctor_store_without_layout_names_store_status_init(tmp_path, monkeypatch, capsys):
    (tmp_path / "store").mkdir()
    rc = _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "store"))
    assert rc == 1
    assert "rosy_ml store-status --init" in capsys.readouterr().out


def test_doctor_without_store_or_hf_says_so(tmp_path, monkeypatch, capsys):
    assert _doctor(tmp_path, monkeypatch, Robot()) == 0
    assert "! no store" in capsys.readouterr().out


def test_doctor_replay_clips_are_required_with_a_store(tmp_path, monkeypatch, capsys):
    _store_with(tmp_path)
    assert _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "store"),
                   clips=0) == 1
    assert "replay" in capsys.readouterr().out


def test_store_status_lists_datasets_and_counts(tmp_path, monkeypatch, capsys):
    _, sha = _store_with(tmp_path)
    _init(tmp_path, "--store", str(tmp_path / "store"), monkeypatch=monkeypatch)
    assert rosy_ml.main(["store-status"]) == 0
    out = capsys.readouterr().out
    assert f"store:lane@{sha}" in out
    assert "inbox: 1 ready, 1 waiting" in out and "accepted: 0" in out and "rejected: 0" in out


def test_store_status_init_creates_the_layout(tmp_path, monkeypatch, capsys):
    _init(tmp_path, "--store", str(tmp_path / "store"), monkeypatch=monkeypatch)
    assert rosy_ml.main(["store-status"]) == 1          # missing: not created silently
    (tmp_path / "store").mkdir()
    assert rosy_ml.main(["store-status", "--init"]) == 0
    assert (tmp_path / "store" / "models" / "inbox").is_dir()
    assert (tmp_path / "store" / "datasets").is_dir()


def test_store_status_without_a_store_is_refused(tmp_path, monkeypatch, capsys):
    _init(tmp_path, monkeypatch=monkeypatch)
    assert rosy_ml.main(["store-status"]) == 2
    assert "rosy_ml init --store" in capsys.readouterr().out


def test_intake_passes_the_store_for_inbox_refs(tmp_path, monkeypatch):
    _init(tmp_path, "--store", str(tmp_path / "store"), monkeypatch=monkeypatch)
    got = {}
    fake = types.ModuleType("intake")
    fake.DEFAULT_GATE, fake.ROOT = "g", "/repo"
    fake.run = lambda source, **kw: (got.update(kw, source=source), (0, {}))[1]
    monkeypatch.setitem(sys.modules, "intake", fake)
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # never needed here
    assert rosy_ml.main(["intake", "store-inbox:m1"]) == 0
    assert got["source"] == "store-inbox:m1" and got["store"] == str(tmp_path / "store")
    assert got["downloader"] is None


def test_doctor_on_the_site_requires_onnx_and_onnxruntime(tmp_path, monkeypatch, capsys):
    key = tmp_path / "id"
    key.write_text("k")
    if os.name != "nt":
        key.chmod(0o600)
    wc = tmp_path / "model-watch.yaml"
    wc.write_text(json.dumps({"store": str(tmp_path / "store"),
                              "robots": [{"name": "pinky-a", "host": "h"}],
                              "ssh": {"identity": str(key), "known_hosts": str(tmp_path / "kh")},
                              "intake_out": str(tmp_path), "state_file": str(tmp_path / "s")}))
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    r = Robot()
    rc = rosy_ml.main(["doctor", "--watch-config", str(wc)], runner=r.runner, connect=r.connect,
                      find_spec=lambda n: None if n == "onnx" else object(),
                      resolve=lambda h, p: [])
    out = capsys.readouterr().out
    assert rc == 1 and "onnx importable" in out


def test_doctor_local_onnx_is_advisory_for_an_operator(tmp_path, monkeypatch, capsys):
    _init(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    r = Robot()
    assert rosy_ml.main(["doctor", "pinky-a"], runner=r.runner, connect=r.connect,
                        find_spec=lambda n: None if n == "onnx" else object()) == 0
    assert "onnx importable" in capsys.readouterr().out


def test_fetch_http_uses_the_operator_token_and_port(tmp_path, monkeypatch):
    # harvest's core_token_file is a viewer token; fetch needs its own Operator token key.
    cfg, rc = _init(tmp_path, "--core-token-file", str(tmp_path / "core.token"),
                    "--core-operator-token-file", str(tmp_path / "op.token"), monkeypatch=monkeypatch)
    assert rc == 0 and yaml.safe_load(cfg.read_text())["core_operator_token_file"] == str(tmp_path / "op.token")
    seen = []
    fake = types.ModuleType("fetch_http")
    fake.main = lambda argv: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "fetch_http", fake)
    assert rosy_ml.main(["fetch", "pinky-a", "--http", "--dest", str(tmp_path / "raw")]) == 0
    assert seen[0][0] == "http://10.0.0.11:8080"
    assert seen[0][seen[0].index("--token-file") + 1] == str(tmp_path / "op.token")
    assert seen[0][seen[0].index("--dest") + 1] == str(tmp_path / "raw")
    with pytest.raises(SystemExit):
        rosy_ml.main(["fetch", "pinky-a"])          # --http is required: SSH stays `harvest`


def test_fetch_http_needs_an_operator_token(tmp_path, monkeypatch, capsys):
    _init(tmp_path, "--core-token-file", str(tmp_path / "core.token"), monkeypatch=monkeypatch)
    assert rosy_ml.main(["fetch", "pinky-a", "--http"]) == 2
    assert "--core-operator-token-file" in capsys.readouterr().out


def test_doctor_checks_the_gate_eval_set_when_one_is_set(tmp_path, monkeypatch, capsys):
    _store_with(tmp_path)
    ev = tmp_path / "evalsets" / "ev" / ("c" * 64)
    monkeypatch.setattr(rosy_ml, "_gate_eval_set", lambda cfg: ev)
    assert _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "store")) == 1
    assert "eval set" in capsys.readouterr().out
    ev.mkdir(parents=True)
    (ev / "manifest.json").write_text("{}")
    assert _doctor(tmp_path, monkeypatch, Robot(), "--store", str(tmp_path / "store")) == 0


def test_gate_eval_set_is_none_with_the_default_gate(tmp_path):
    pytest.importorskip("cv2")
    assert rosy_ml._gate_eval_set({}) is None
