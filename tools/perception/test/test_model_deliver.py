"""Task 9: model delivery to the robot (D-356); rosy + sudo -n + pinned SSH (D-373 #6)."""
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "perception" / "model", ROOT / "tools" / "perception" / "training"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deliver  # noqa: E402
import export_cell  # noqa: E402

REV = "lane-seg-20260930-abcd1234"
STAGE = "/tmp/rosy-model.AbC12345"
SSH = ["--identity", "/keys/id", "--known-hosts", "/keys/kh"]
ROOT_M = "/var/lib/rosy/models"
S = "sudo -n"


class FakeRunner:
    """Answers the prepare step with a mktemp path; returncode applies to every call."""

    def __init__(self, returncode=0, stdout=None):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        self.kwargs = getattr(self, "kwargs", []) + [kw]

        class R:
            pass

        r = R()
        out = self.stdout
        if out is None:
            out = STAGE + "\n" if "mktemp" in cmd[-1] else ""
        r.returncode, r.stdout, r.stderr = self.returncode, out, ""
        return r


def _model(models: Path, verdict: str, files=None) -> str:
    onnx = models.parent / "src.onnx"
    onnx.write_bytes(b"fake-onnx")
    tmp = models.parent / "tmp"
    doc = export_cell.write_manifest(
        tmp, onnx_path=onnx, classes=[("bg", "background"), ("lane", "lane_marking")],
        color="rgb", scale=1 / 255, mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="org/ds",
        dataset_revision="a" * 40, camera_profile_revision="cam-1", trainer="t",
        date="20260930")
    rev = doc["model_revision"]
    models.mkdir(parents=True, exist_ok=True)
    tmp.rename(models / rev)
    if files is None:  # what intake records: the manifest-verified files
        files = [{"name": f.name, "sha256": f.sha256}
                 for f in deliver.load_manifest(models / rev).files]
    (models / rev / "intake_report.json").write_text(
        json.dumps({"model_revision": rev, "verdict": verdict, "files": files}),
        encoding="utf-8")
    return rev


REPORT = ("e" * 64, "intake_report.json")


def _push_script(**kw):
    return deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")],
                                 report=REPORT, stage=f"{STAGE}/{REV}", **kw)


def test_remote_push_trap_is_set_before_anything_can_fail():
    lines = _push_script().splitlines()
    assert lines[0] == "set -e" and lines[1].startswith("trap ")


def test_remote_push_existing_final_is_judged_on_model_files_only():
    s = _push_script()
    root = ROOT_M
    guard = s[s.index(f"if {S} test -d {root}/{REV}; then"):s.index(f"else {S} mv {root}/{REV}.partial")]
    first_if = guard.splitlines()[1]
    assert f"  {root}/{REV}/model.onnx" in first_if
    assert "intake_report.json" not in first_if  # a new report never quarantines a folder
    # matching model: only the report is replaced, atomically
    put = guard.index(f"{S} install -o root -g rosy-camera -m 0640 {STAGE}/{REV}/intake_report.json "
                      f"{root}/{REV}/intake_report.json.tmp")
    assert put < guard.index(f"{S} mv {root}/{REV}/intake_report.json.tmp "
                             f"{root}/{REV}/intake_report.json")
    # the installed folder is then checked in full, report included
    last_check = s.rindex("sha256sum -c")
    last = s[s.rindex("printf", 0, last_check):last_check]
    assert f"{'e' * 64}  {root}/{REV}/intake_report.json" in last


LOCKED = f"{S} flock -E 75 -w 30 {ROOT_M}/.lock sh -c "
AUDIT = {"operator": "ana", "host_of_operator": "op-pc", "tool_commit": "c" * 40}


def test_remote_push_script_installs_partial_then_pointer_swap():
    s = _push_script()
    root = ROOT_M
    staged_check = s.index(f"{'f' * 64}  {STAGE}/{REV}/model.onnx")
    locked = s.index(LOCKED)
    mkdir = s.index(f"install -d -o root -g rosy-camera -m 0750 {root}/{REV}.partial")
    put = s.index(f"install -o root -g rosy-camera -m 0640 {STAGE}/{REV}/model.onnx "
                  f"{root}/{REV}.partial/model.onnx")
    partial_check = s.index(f"{'f' * 64}  {root}/{REV}.partial/model.onnx")
    mv_final = s.index(f"mv {root}/{REV}.partial {root}/{REV}")
    ptr_put = s.index(f"install -o root -g rosy-camera -m 0640 {STAGE}/shadow "
                      f"{root}/shadow.tmp")
    swap = s.index(f"mv {root}/shadow.tmp {root}/shadow")
    history = s.index(f"tee -a {root}/history.jsonl")
    assert staged_check < locked < mkdir < put < partial_check < mv_final < ptr_put < swap
    assert swap < history
    prev = s.index(f"install -o root -g rosy-camera -m 0640 {root}/shadow "
                   f"{root}/shadow.previous.tmp")
    assert prev < s.index(f"mv {root}/shadow.previous.tmp {root}/shadow.previous") < swap
    assert s.index("sync", swap) > swap
    assert f"trap 'rm -rf -- {STAGE}' EXIT" in s


def test_remote_push_root_work_runs_as_root_under_the_lock():
    s = _push_script()
    outer = s[:s.index(LOCKED)]
    for line in outer.splitlines():
        if ROOT_M in line and "trap" not in line:
            assert line.startswith(S), line
    # created in place (append + chown/chmod), never unlinked or replaced
    assert (f"{S} sh -c ': >> {ROOT_M}/.lock; chown root:rosy-camera {ROOT_M}/.lock; "
            f"chmod 0660 {ROOT_M}/.lock'") in outer
    assert f"rm -f {ROOT_M}/.lock" not in s and f"{ROOT_M}/.lock.tmp" not in s
    assert "busy for 30 s" in s and "exit $rc" in s
    local = _push_script(privileged=False)
    assert "sudo" not in local and " -o root" not in local and " -m 07" not in local
    assert "flock -E 75 -w 30 " in local


def test_remote_push_existing_final_is_judged_on_model_files_only():
    s = _push_script()
    root = ROOT_M
    guard = s[s.index(f"if test -d {root}/{REV}; then"):s.index(f"else mv {root}/{REV}.partial")]
    first_if = guard.splitlines()[1]
    assert f"  {root}/{REV}/model.onnx" in first_if
    assert "intake_report.json" not in first_if  # a new report never quarantines a folder
    put = guard.index(f"install -o root -g rosy-camera -m 0640 {STAGE}/{REV}/intake_report.json "
                      f"{root}/{REV}/intake_report.json.tmp")
    assert put < guard.index(f"mv {root}/{REV}/intake_report.json.tmp "
                             f"{root}/{REV}/intake_report.json")
    last_check = s.rindex("sha256sum -c")
    last = s[s.rindex("printf", 0, last_check):last_check]
    assert f"{'e' * 64}  {root}/{REV}/intake_report.json" in last


def test_remote_push_reverifies_existing_final_and_quarantines_bad():
    s = _push_script()
    root = ROOT_M
    assert f"mv {root}/{REV} {root}/{REV}.bad.$$" in s
    assert s.count("sha256sum -c") >= 4
    last_check = s.rindex("sha256sum -c")
    assert s.index(f"mv {root}/{REV}.partial") < last_check
    assert f"  {root}/{REV}/model.onnx" in s[s.rindex("printf", 0, last_check):last_check]
    assert last_check < s.index(f"mv {root}/shadow.tmp {root}/shadow")


def test_history_line_quotes_the_audit_fields():
    evil = {"operator": "o'x $(reboot) \"q\"", "host_of_operator": "h;rm", "tool_commit": None}
    s = _push_script(audit=evil)
    body = shlex.split(s[s.index(LOCKED):].split(" || { rc=$?;")[0])[-1]  # the sh -c script
    (printf,) = [ln for ln in body.splitlines() if "tee -a" in ln]
    words = shlex.split(printf)
    # each audit field is exactly one single-quoted word: no expansion on the robot
    assert json.dumps(evil["operator"]) in words
    assert json.dumps(evil["host_of_operator"]) in words and "null" in words


def test_remote_push_same_rev_keeps_previous():
    s = _push_script()
    guard = s.index(f'!= {ROOT_M}/{REV} ]')
    assert guard < s.index(f"{ROOT_M}/shadow.previous.tmp")


def test_remote_script_quotes_revision_with_space():
    s = deliver.remote_script("push", "bad rev", checks=[("f" * 64, "model.onnx")],
                              report=REPORT, stage=f"{STAGE}/bad rev")
    assert shlex.quote("/var/lib/rosy/models/bad rev.partial") in s
    assert shlex.quote("/var/lib/rosy/models/bad rev") in s
    # outside the quoted sha256sum lines, the path only appears quoted
    assert " /var/lib/rosy/models/bad rev" not in re.sub(r"'[0-9a-f]{64}  [^']*'", "", s)


def test_remote_prepare_is_user_temp_only():
    s = deliver.remote_script("prepare", REV)
    assert "mktemp -d /tmp/rosy-model." in s
    assert "sudo" not in s and ROOT_M not in s


def test_remote_rollback_refuses_without_previous_and_is_audited():
    s = deliver.remote_script("rollback", None, audit=AUDIT)
    assert LOCKED in s
    assert "shadow.previous" in s and "exit 1" in s
    assert f"mv {ROOT_M}/shadow.previous {ROOT_M}/shadow" in s
    assert f"tee -a {ROOT_M}/history.jsonl" in s and '"rollback"' in s


def test_remote_status_tails_history():
    s = deliver.remote_script("status", None, history=3)
    assert f"{S} tail -n 3 {ROOT_M}/history.jsonl" in s


def test_remote_script_unknown_action():
    with pytest.raises(ValueError):
        deliver.remote_script("nuke", REV)


def test_push_script_needs_checks_and_stage():
    with pytest.raises(ValueError):
        deliver.remote_script("push", REV, stage=f"{STAGE}/{REV}")
    with pytest.raises(ValueError):
        deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")], report=REPORT)
    with pytest.raises(ValueError):
        deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")],
                              stage=f"{STAGE}/{REV}")


def test_push_refuses_failed_intake(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "fail")
    runner = FakeRunner()
    rc = deliver.main(["push", "robot", rev, "--models", str(models), *SSH], runner=runner)
    assert rc != 0
    assert runner.calls == []


def test_push_refuses_missing_report(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    (models / rev / "intake_report.json").unlink()
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) != 0
    assert runner.calls == []


@pytest.mark.parametrize("files", [
    [],  # a report from before intake recorded files
    [{"name": "model.onnx", "sha256": "0" * 64}],  # the model changed after intake
])
def test_push_refuses_report_files_differing_from_manifest(tmp_path, files):
    models = tmp_path / "models"
    rev = _model(models, "pass", files=files)
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) == 2
    assert runner.calls == []


def test_push_refuses_unsafe_revision(tmp_path):
    runner = FakeRunner()
    assert deliver.main(["push", "robot", "../x", "--models", str(tmp_path), *SSH],
                        runner=runner) != 0
    assert runner.calls == []


def test_push_runs_prepare_scp_install(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    rc = deliver.main(["push", "robot", rev, "--models", str(models), *SSH], runner=runner)
    assert rc == 0
    assert [c[0] for c in runner.calls] == ["ssh", "scp", "ssh"]
    assert runner.calls[1][-1] == f"rosy@robot:{STAGE}/{rev}"
    assert runner.calls[1][-2] == str(models / rev)
    push = runner.calls[2][-1]
    assert "sha256sum -c" in push
    # manifest and intake report are pinned too, not just the weights
    for name in ("model_manifest.json", "intake_report.json"):
        digest = hashlib.sha256((models / rev / name).read_bytes()).hexdigest()
        assert f"{digest}  {STAGE}/{rev}/{name}" in push


def test_push_refuses_unexpected_stage_path(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner(stdout="/var/lib/rosy/models\n")
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) != 0
    assert len(runner.calls) == 1


def test_push_cleans_stage_when_scp_fails(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")

    class ScpFails(FakeRunner):
        def __call__(self, cmd, **kw):
            r = super().__call__(cmd, **kw)
            if cmd[0] == "scp":
                r.returncode = 1
            return r

    runner = ScpFails()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) == 1
    assert [c[0] for c in runner.calls] == ["ssh", "scp", "ssh"]
    assert runner.calls[2][-1] == f"rm -rf -- {STAGE}"


def test_push_stops_on_failed_step(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner(returncode=1)
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) != 0
    assert len(runner.calls) == 1


def test_timeouts_default_600_push_60_status_and_override(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) == 0
    assert [kw["timeout"] for kw in runner.kwargs] == [600, 600, 600]
    runner = FakeRunner()
    assert deliver.main(["status", "robot", *SSH], runner=runner) == 0
    assert runner.kwargs[0]["timeout"] == 60
    runner = FakeRunner()
    assert deliver.main(["status", "robot", "--timeout", "5", *SSH], runner=runner) == 0
    assert runner.kwargs[0]["timeout"] == 5


def test_timeout_is_a_failed_step(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    calls = []

    def hang(cmd, **kw):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=hang) == 1
    assert len(calls) == 1


def test_rollback_and_status_run_ssh():
    runner = FakeRunner()
    assert deliver.main(["rollback", "robot", *SSH], runner=runner) == 0
    assert runner.calls[0][-2] == "rosy@robot"
    assert "shadow.previous" in runner.calls[0][-1]
    runner = FakeRunner(stdout="shadow: /var/lib/rosy/models/x\n")
    assert deliver.main(["status", "robot", *SSH], runner=runner) == 0
    assert f"{S} cat" in runner.calls[0][-1]


def test_operator_is_recorded_and_status_history_flag(tmp_path, monkeypatch):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    monkeypatch.setattr(deliver.getpass, "getuser", lambda: "osuser")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) == 0
    assert shlex.quote(json.dumps("osuser")) in runner.calls[2][-1]
    runner = FakeRunner()
    assert deliver.main(["rollback", "robot", "--operator", "site:fleet-1", *SSH],
                        runner=runner) == 0
    assert shlex.quote(json.dumps("site:fleet-1")) in runner.calls[0][-1]
    runner = FakeRunner()
    assert deliver.main(["status", "robot", "--history", "2", *SSH], runner=runner) == 0
    assert "tail -n 2 " in runner.calls[0][-1]


def test_missing_identity_on_linux_is_refused(monkeypatch):
    monkeypatch.setattr(deliver.operator_ssh.sys, "platform", "linux")
    monkeypatch.delenv("ROSY_OPERATOR_KEY", raising=False)
    monkeypatch.delenv("ROSY_KNOWN_HOSTS", raising=False)
    runner = FakeRunner()
    assert deliver.main(["status", "robot"], runner=runner) == 2
    assert runner.calls == []


@pytest.mark.parametrize("argv", [
    ["rollback", "-oProxyCommand=x"],
    ["rollback", "robot", "--user", "-x"],
    ["rollback", "robot", "--user", "a b"],
    ["status", "ro bot"],
    ["status", "robot", "--root", "relative/models"],
    ["status", "robot", "--root", "/var/lib/rosy models"],
    ["status", "robot", "--root", "/var/$(x)"],
    ["status", "robot", "--root", "/var/lib/../etc"],
    ["status", "robot", "--root", "/.."],
])
def test_rejects_unsafe_host_user_root(argv):
    runner = FakeRunner()
    try:
        rc = deliver.main([*argv, *SSH], runner=runner)
    except SystemExit as exc:  # argparse refusing an option-looking host is fine too
        rc = exc.code
    assert rc != 0
    assert runner.calls == []


def test_ssh_and_scp_are_batch_pinned_and_end_options(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models), *SSH],
                        runner=runner) == 0
    for cmd in runner.calls:
        assert cmd[cmd.index("-i") + 1] == "/keys/id"
        for opt in ("BatchMode=yes", "IdentitiesOnly=yes", "UserKnownHostsFile=/keys/kh",
                    "StrictHostKeyChecking=yes"):
            assert opt in cmd
    assert runner.calls[0][-3:-1] == ["--", "rosy@robot"]
    assert runner.calls[1][0] == "scp" and "-r" in runner.calls[1]
    assert runner.calls[1][-3] == "--"


# --- the generated push script, executed for real -------------------------------------------
# Locally there is no root and no rosy-camera group: privileged=False. Production
# (deliver.main) always uses sudo -n root:rosy-camera, asserted above.

# Git Bash has no flock: the shim runs the command without locking. Only the
# concurrency tests need the real one and skip without it.
FLOCK_SHIM = (
    'command -v flock >/dev/null 2>&1 || flock() { '
    'while [ $# -gt 0 ]; do case "$1" in -E|-w) shift 2;; -*) shift;; *) break;; esac; done; '
    'shift; "$@"; }\n')


def _has_flock(bash) -> bool:
    return subprocess.run([bash, "-c", "command -v flock"], capture_output=True).returncode == 0


def _bash_env():
    """(bash, to_posix) for a bash with sha256sum, else None. Git Bash needs cygpath for paths."""
    bash = shutil.which("bash")
    if not bash:
        return None
    probe = subprocess.run([bash, "-c", "command -v sha256sum && command -v install"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return None
    if sys.platform != "win32":
        return bash, str
    cyg = shutil.which("cygpath")
    if not cyg:
        return None  # e.g. WSL bash: Windows paths do not map; exercised on Linux/WSL instead

    def to_posix(path):
        return subprocess.run([cyg, "-u", str(path)], capture_output=True, text=True,
                              check=True).stdout.strip()
    return bash, to_posix


@pytest.fixture
def remote(tmp_path):
    env = _bash_env()
    if env is None:
        pytest.skip("needs bash with sha256sum and install (and cygpath on Windows)")
    bash, to_posix = env
    root = tmp_path / "models"
    root.mkdir()
    stage_dir = tmp_path / "stage"
    good = b"model-bytes"
    checks = [(hashlib.sha256(good).hexdigest(), "model.onnx")]
    report = {"text": b"report-1"}

    def run(checks=checks, audit=None, unless_held=False):
        rep = (hashlib.sha256(report["text"]).hexdigest(), "intake_report.json")
        script = deliver.remote_script("push", REV, to_posix(root), checks=checks, report=rep,
                                       stage=to_posix(stage_dir / REV), audit=audit,
                                       unless_held=unless_held, privileged=False)
        return subprocess.run([bash, "-c", FLOCK_SHIM + script], capture_output=True, text=True)

    def stage(content, folder=None, report_text=None):
        where = stage_dir / REV if folder is None else root / folder
        where.mkdir(parents=True)
        (where / "model.onnx").write_bytes(content)
        (where / "intake_report.json").write_bytes(report_text or report["text"])

    run.report = report

    return root, to_posix, run, stage, good, stage_dir


def test_remote_script_fresh_install_sets_pointer(remote):
    root, to_posix, run, stage, good, stage_dir = remote
    stage(good)
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / REV / "model.onnx").read_bytes() == good
    assert not (root / f"{REV}.partial").exists()
    assert (root / "shadow").read_text() == f"{to_posix(root)}/{REV}"
    assert not (root / "shadow.previous").exists()
    assert not stage_dir.exists()  # the user temp dir is removed on exit


def test_remote_script_replaces_corrupt_existing_rev(remote):
    root, to_posix, run, stage, good, _ = remote
    stage(b"corrupt", REV)
    stage(good)
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / REV / "model.onnx").read_bytes() == good
    bad = list(root.glob(f"{REV}.bad.*"))
    assert len(bad) == 1 and (bad[0] / "model.onnx").read_bytes() == b"corrupt"
    assert (root / "shadow").read_text() == f"{to_posix(root)}/{REV}"


def test_remote_script_failing_checksum_leaves_pointer_untouched(remote):
    root, to_posix, run, stage, good, stage_dir = remote
    (root / "shadow").write_text("/old/model")
    stage(b"tampered")
    r = run()
    assert r.returncode != 0
    assert (root / "shadow").read_text() == "/old/model"
    assert not (root / "shadow.tmp").exists() and not (root / "shadow.previous").exists()
    assert not (root / REV).exists() and not (root / f"{REV}.partial").exists()
    assert not stage_dir.exists()


def test_remote_script_moves_old_pointer_to_previous(remote):
    root, to_posix, run, stage, good, _ = remote
    (root / "shadow").write_text("/old/model")
    stage(good)
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / "shadow.previous").read_text() == "/old/model"
    assert (root / "shadow").read_text() == f"{to_posix(root)}/{REV}"


def test_remote_script_repush_live_rev_keeps_previous(remote):
    root, to_posix, run, stage, good, _ = remote
    stage(good, REV)
    (root / "shadow").write_text(f"{to_posix(root)}/{REV}")
    (root / "shadow.previous").write_text("/older/model")
    stage(good)
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / "shadow.previous").read_text() == "/older/model"
    assert not (root / f"{REV}.partial").exists()


def test_remote_script_repush_with_new_report_keeps_folder(remote):
    root, to_posix, run, stage, good, _ = remote
    stage(good, REV, report_text=b"report-old")
    (root / "shadow").write_text(f"{to_posix(root)}/{REV}")
    run.report["text"] = b"report-new"
    stage(good)
    r = run()
    assert r.returncode == 0, r.stderr
    assert not list(root.glob(f"{REV}.bad.*"))
    assert (root / REV / "intake_report.json").read_bytes() == b"report-new"
    assert (root / REV / "model.onnx").read_bytes() == good
    assert not (root / f"{REV}.partial").exists()
    assert not (root / REV / "intake_report.json.tmp").exists()


def test_remote_script_appends_a_parseable_history_line(remote):
    root, to_posix, run, stage, good, _ = remote
    (root / "shadow").write_text("/old/lane-seg-20260901-00000000")
    stage(good)
    who = {"operator": "o'x $(echo pwned) \"q\"", "host_of_operator": "pc", "tool_commit": None}
    r = run(audit=who)
    assert r.returncode == 0, r.stderr
    (line,) = (root / "history.jsonl").read_text().splitlines()
    rec = json.loads(line)
    assert rec["action"] == "push" and rec["revision"] == REV
    assert rec["previous"] == "lane-seg-20260901-00000000"
    assert rec["operator"] == who["operator"] and rec["tool_commit"] is None
    assert rec["ts"].endswith("Z")


def _two_pushes(tmp_path, bash, to_posix, revs):
    root = tmp_path / "models"
    root.mkdir()
    good = b"model-bytes"
    checks = [(hashlib.sha256(good).hexdigest(), "model.onnx")]
    rep = (hashlib.sha256(b"r").hexdigest(), "intake_report.json")
    procs = []
    for i, rev in enumerate(revs):
        stage = tmp_path / f"stage{i}" / rev
        stage.mkdir(parents=True)
        (stage / "model.onnx").write_bytes(good)
        (stage / "intake_report.json").write_bytes(b"r")
        script = deliver.remote_script("push", rev, to_posix(root), checks=checks, report=rep,
                                       stage=to_posix(stage), privileged=False,
                                       audit={"operator": f"op{i}"})
        procs.append(subprocess.Popen([bash, "-c", script], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True))
    return root, [(p.wait(timeout=120), p.stderr.read()) for p in procs]


def test_concurrent_pushes_serialise_under_the_lock(tmp_path):
    env = _bash_env()
    if env is None or not _has_flock(env[0]):
        pytest.skip("needs bash with flock (not in Git Bash on win32)")
    bash, to_posix = env
    revs = ["lane-seg-20260930-aaaaaaaa", "lane-seg-20260930-bbbbbbbb"]
    root, results = _two_pushes(tmp_path, bash, to_posix, revs)
    assert all(rc == 0 for rc, _ in results), results
    lines = [json.loads(x) for x in (root / "history.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    first, second = lines
    assert first["previous"] == "" and second["previous"] == first["revision"]
    assert (root / "shadow").read_text().endswith(second["revision"])
    assert (root / "shadow.previous").read_text().endswith(first["revision"])


def test_busy_lock_fails_clearly(tmp_path):
    env = _bash_env()
    if env is None or not _has_flock(env[0]):
        pytest.skip("needs bash with flock (not in Git Bash on win32)")
    bash, to_posix = env
    root = tmp_path / "models"
    root.mkdir()
    (root / ".lock").write_text("")
    (root / "shadow.previous").write_text("/x/lane-seg-20260930-aaaaaaaa")
    holder = subprocess.Popen(["flock", str(root / ".lock"), "sleep", "5"])
    try:
        import time
        time.sleep(0.5)
        script = deliver.remote_script("rollback", None, to_posix(root), privileged=False,
                                       lock_wait=1, audit={"operator": "op"})
        r = subprocess.run([bash, "-c", script], capture_output=True, text=True, timeout=60)
    finally:
        holder.kill()
    assert r.returncode == 75 and "busy" in r.stderr
    assert (root / "shadow.previous").exists()  # nothing changed


# --- hold file, exit codes 75/76, history failure (D-373 decision 7) ------------------------

HOLD = f"{ROOT_M}/hold"


def _body(script):
    return shlex.split(script[script.index(LOCKED):].split(" || { rc=$?;")[0])[-1]


def test_manual_push_writes_the_hold_before_the_pointer_moves():
    body = _body(_push_script(audit=AUDIT))
    hold = body.index(f"mv {HOLD}.tmp {HOLD}")
    assert body.index(f"(: >> {ROOT_M}/history.jsonl)") < hold  # appendable, checked first
    assert hold < body.index(f"mv {ROOT_M}/shadow.tmp {ROOT_M}/shadow")
    assert "manual push" in body and f"exit 76" not in body


def test_site_push_unless_held_checks_first_and_writes_no_hold():
    body = _body(_push_script(audit=AUDIT, unless_held=True))
    gate = body.index(f"if test -e {HOLD}; then")
    assert gate < body.index(f"rm -rf {ROOT_M}/{REV}.partial")
    assert "exit 76" in body[gate:gate + 200]
    assert f"mv {HOLD}.tmp {HOLD}" not in body


def test_inner_75_and_76_are_remapped():
    body = _body(_push_script(audit=AUDIT))
    assert "set +e\n(\nset -e" in body and "case $rc in 75|76) rc=1;; esac" in body


def test_rollback_holds_and_release_hold_only_removes_it():
    rb = _body(deliver.remote_script("rollback", None, audit=AUDIT))
    assert rb.index(f"mv {HOLD}.tmp {HOLD}") < rb.index(f"mv {ROOT_M}/shadow.previous {ROOT_M}/shadow")
    rel = deliver.remote_script("release-hold", None, audit=AUDIT)
    body = _body(rel)
    assert f"rm -f {HOLD}" in body and '"release-hold"' in body
    assert "mv " not in body  # the pointer is not touched


def test_history_failure_after_the_move_is_reported():
    body = _body(_push_script(audit=AUDIT))
    assert "pointer changed, history not written" in body and "exit 3" in body


def test_status_and_observe_read_the_hold_file():
    assert f"{S} cat {HOLD}" in deliver.remote_script("status", None)
    assert f"{S} cat {HOLD}" in deliver.remote_script("observe", None)


def test_observe_parses_pointer_and_hold():
    hold = {"by": "ana", "host": "pc", "ts": "t", "action": "rollback", "revision": "r0",
            "reason": "manual rollback"}
    runner = FakeRunner(stdout=f"{ROOT_M}/r0\n--- hold\n{json.dumps(hold)}\n")
    got = deliver.observe("robot", identity="/keys/id", known_hosts="/keys/kh", runner=runner)
    assert got == {"shadow": "r0", "hold": hold}
    assert runner.calls[0][-2] == "rosy@robot" and runner.kwargs[0]["timeout"] == 60
    assert deliver.parse_observation("\n--- hold\n") == {"shadow": None, "hold": None}
    with pytest.raises(RuntimeError):
        deliver.observe("robot", identity="/k", known_hosts="/kh", runner=FakeRunner(returncode=1))


def test_release_hold_cli():
    runner = FakeRunner()
    assert deliver.main(["release-hold", "robot", "--operator", "ana", *SSH], runner=runner) == 0
    assert '"release-hold"' in runner.calls[0][-1]


@pytest.mark.parametrize("rc, expected", [(75, 75), (76, 76), (3, 1), (1, 1)])
def test_push_passes_busy_and_held_through(tmp_path, rc, expected):
    models = tmp_path / "models"
    rev = _model(models, "pass")

    class LastFails(FakeRunner):
        def __call__(self, cmd, **kw):
            r = super().__call__(cmd, **kw)
            if len(self.calls) == 3:
                r.returncode = rc
            return r

    runner = LastFails()
    assert deliver.main(["push", "robot", rev, "--models", str(models), "--unless-held", *SSH],
                        runner=runner) == expected
    assert "if test -e /var/lib/rosy/models/hold" in runner.calls[2][-1]


def test_rollback_busy_is_75():
    assert deliver.main(["rollback", "robot", *SSH], runner=FakeRunner(returncode=75)) == 75


# executed under bash (flock shim in Git Bash)

def _run_script(bash, script):
    return subprocess.run([bash, "-c", FLOCK_SHIM + script], capture_output=True, text=True)


def test_manual_push_leaves_a_parseable_hold(remote):
    root, to_posix, run, stage, good, _ = remote
    stage(good)
    r = run(audit={"operator": "ana", "host_of_operator": "pc"})
    assert r.returncode == 0, r.stderr
    hold = json.loads((root / "hold").read_text())
    assert hold["by"] == "ana" and hold["action"] == "push" and hold["revision"] == REV
    assert hold["reason"] == "manual push" and hold["ts"].endswith("Z")


def test_held_site_push_touches_nothing(remote, tmp_path):
    root, to_posix, run, stage, good, stage_dir = remote
    (root / "hold").write_text('{"by": "ana"}')
    (root / "shadow").write_text("/old/model")
    stage(good)
    r = run(unless_held=True)
    assert r.returncode == 76 and "held" in r.stderr
    assert (root / "shadow").read_text() == "/old/model"
    assert not (root / REV).exists() and not (root / f"{REV}.partial").exists()
    assert not (root / "history.jsonl").exists()


def test_release_hold_removes_the_file_and_keeps_the_pointer(tmp_path):
    env = _bash_env()
    if env is None:
        pytest.skip("needs bash")
    bash, to_posix = env
    root = tmp_path / "models"
    root.mkdir()
    (root / "hold").write_text("{}")
    (root / "shadow").write_text("/x/lane-seg-20260930-aaaaaaaa")
    r = _run_script(bash, deliver.remote_script("release-hold", None, to_posix(root),
                                                privileged=False, audit={"operator": "bo"}))
    assert r.returncode == 0, r.stderr
    assert not (root / "hold").exists()
    assert (root / "shadow").read_text() == "/x/lane-seg-20260930-aaaaaaaa"
    rec = json.loads((root / "history.jsonl").read_text())
    assert rec["action"] == "release-hold" and rec["operator"] == "bo"


def test_unappendable_history_changes_nothing(remote):
    root, to_posix, run, stage, good, _ = remote
    (root / "history.jsonl").mkdir()  # cannot be appended to
    (root / "shadow").write_text("/old/model")
    stage(good)
    r = run()
    assert r.returncode == 3 and "not appendable" in r.stderr
    assert (root / "shadow").read_text() == "/old/model" and not (root / "hold").exists()
