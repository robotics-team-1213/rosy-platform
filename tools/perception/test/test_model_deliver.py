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


def test_remote_push_script_installs_partial_then_pointer_swap():
    s = _push_script()
    root = ROOT_M
    staged_check = s.index(f"{'f' * 64}  {STAGE}/{REV}/model.onnx")
    mkdir = s.index(f"{S} install -d -o root -g rosy-camera -m 0750 {root}/{REV}.partial")
    put = s.index(f"{S} install -o root -g rosy-camera -m 0640 {STAGE}/{REV}/model.onnx "
                  f"{root}/{REV}.partial/model.onnx")
    partial_check = s.index(f"{'f' * 64}  {root}/{REV}.partial/model.onnx")
    mv_final = s.index(f"{S} mv {root}/{REV}.partial {root}/{REV}")
    ptr_put = s.index(f"{S} install -o root -g rosy-camera -m 0640 {STAGE}/shadow "
                      f"{root}/shadow.tmp")
    swap = s.index(f"{S} mv {root}/shadow.tmp {root}/shadow")
    assert staged_check < mkdir < put < partial_check < mv_final < ptr_put < swap
    prev = s.index(f"{S} install -o root -g rosy-camera -m 0640 {root}/shadow "
                   f"{root}/shadow.previous.tmp")
    assert prev < s.index(f"{S} mv {root}/shadow.previous.tmp {root}/shadow.previous") < swap
    assert s.index("sync", swap) > swap
    assert f"trap 'rm -rf -- {STAGE}' EXIT" in s


def test_remote_push_every_root_write_goes_through_sudo():
    s = _push_script()
    for line in s.splitlines():
        for verb in ("install ", "mv ", "rm -rf ", "cat "):
            if verb in line and ROOT_M in line and "trap" not in line:
                assert f"{S} {verb}" in line, line
        if "sha256sum -c" in line and ROOT_M in line:
            assert f"{S} sha256sum -c" in line, line
    local = _push_script(privileged=False)
    assert "sudo" not in local and " -o root" not in local and " -m 07" not in local


def test_remote_push_reverifies_existing_final_and_quarantines_bad():
    s = _push_script()
    root = ROOT_M
    assert f"{S} mv {root}/{REV} {root}/{REV}.bad.$$" in s
    # staged, partial, existing final and installed final are all checked
    assert s.count("sha256sum -c") >= 4
    last_check = s.rindex("sha256sum -c")
    assert s.index(f"{S} mv {root}/{REV}.partial") < last_check
    assert f"  {root}/{REV}/model.onnx" in s[s.rindex("printf", 0, last_check):last_check]
    assert last_check < s.index(f"{S} mv {root}/shadow.tmp {root}/shadow")


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


def test_remote_rollback_refuses_without_previous():
    s = deliver.remote_script("rollback", None)
    assert "shadow.previous" in s and "exit 1" in s
    assert f"{S} mv {ROOT_M}/shadow.previous {ROOT_M}/shadow" in s


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

    def run(checks=checks):
        rep = (hashlib.sha256(report["text"]).hexdigest(), "intake_report.json")
        script = deliver.remote_script("push", REV, to_posix(root), checks=checks, report=rep,
                                       stage=to_posix(stage_dir / REV), privileged=False)
        return subprocess.run([bash, "-c", script], capture_output=True, text=True)

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
