"""Task 9: model delivery to the robot (D-356)."""
import hashlib
import json
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


class FakeRunner:
    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)

        class R:
            pass

        r = R()
        r.returncode, r.stdout, r.stderr = self.returncode, self.stdout, ""
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


def test_remote_push_script_partial_then_pointer_swap():
    s = deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")])
    root = "/var/lib/rosy/models"
    assert "sha256sum -c" in s
    assert f"{root}/{REV}.partial" in s
    mv_final = s.index(f"mv {root}/{REV}.partial {root}/{REV}")
    ptr_tmp = s.index(f"> {root}/shadow.tmp")
    swap = s.index(f"mv {root}/shadow.tmp {root}/shadow")
    assert s.index("sha256sum -c") < mv_final < ptr_tmp < swap
    prev = s.index(f"cp {root}/shadow {root}/shadow.previous.tmp")
    assert prev < s.index(f"mv {root}/shadow.previous.tmp {root}/shadow.previous") < swap
    assert s.index("sync", swap) > swap


def test_remote_push_reverifies_existing_final_and_quarantines_bad():
    s = deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")])
    root = "/var/lib/rosy/models"
    assert f"mv {root}/{REV} {root}/{REV}.bad.$$" in s
    # the final folder is verified after install and before the pointer swap
    assert s.count("sha256sum -c") >= 3
    last_check = s.rindex("sha256sum -c")
    assert s.index(f"cd {root}/{REV}", s.index(f"mv {root}/{REV}.partial")) < last_check
    assert last_check < s.index(f"mv {root}/shadow.tmp {root}/shadow")


def test_remote_push_same_rev_keeps_previous():
    s = deliver.remote_script("push", REV, checks=[("f" * 64, "model.onnx")])
    root = "/var/lib/rosy/models"
    guard = s.index(f'!= {root}/{REV} ]')
    assert guard < s.index(f"cp {root}/shadow {root}/shadow.previous.tmp")


def test_remote_script_quotes_revision_with_space():
    s = deliver.remote_script("push", "bad rev", checks=[("f" * 64, "model.onnx")])
    assert shlex.quote("/var/lib/rosy/models/bad rev.partial") in s
    assert shlex.quote("/var/lib/rosy/models/bad rev") in s
    assert " /var/lib/rosy/models/bad rev" not in s


def test_remote_rollback_refuses_without_previous():
    s = deliver.remote_script("rollback", None)
    assert "shadow.previous" in s and "exit 1" in s
    assert "mv /var/lib/rosy/models/shadow.previous /var/lib/rosy/models/shadow" in s


def test_remote_script_unknown_action():
    with pytest.raises(ValueError):
        deliver.remote_script("nuke", REV)


def test_push_refuses_failed_intake(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "fail")
    runner = FakeRunner()
    rc = deliver.main(["push", "robot", rev, "--models", str(models)], runner=runner)
    assert rc != 0
    assert runner.calls == []


def test_push_refuses_missing_report(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    (models / rev / "intake_report.json").unlink()
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models)], runner=runner) != 0
    assert runner.calls == []


@pytest.mark.parametrize("files", [
    [],  # a report from before intake recorded files
    [{"name": "model.onnx", "sha256": "0" * 64}],  # the model changed after intake
])
def test_push_refuses_report_files_differing_from_manifest(tmp_path, files):
    models = tmp_path / "models"
    rev = _model(models, "pass", files=files)
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models)], runner=runner) == 2
    assert runner.calls == []


def test_push_refuses_unsafe_revision(tmp_path):
    runner = FakeRunner()
    assert deliver.main(["push", "robot", "../x", "--models", str(tmp_path)],
                        runner=runner) != 0
    assert runner.calls == []


def test_push_runs_prepare_scp_install(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    rc = deliver.main(["push", "robot", rev, "--models", str(models), "--user", "pinky"],
                      runner=runner)
    assert rc == 0
    assert [c[0] for c in runner.calls] == ["ssh", "scp", "ssh"]
    assert runner.calls[1][-1] == f"pinky@robot:/var/lib/rosy/models/{rev}.partial"
    assert runner.calls[1][-2] == str(models / rev)
    assert "sha256sum -c" in runner.calls[2][-1]


def test_push_stops_on_failed_step(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner(returncode=1)
    assert deliver.main(["push", "robot", rev, "--models", str(models)], runner=runner) != 0
    assert len(runner.calls) == 1


def test_rollback_and_status_run_ssh():
    runner = FakeRunner()
    assert deliver.main(["rollback", "robot"], runner=runner) == 0
    assert runner.calls[0][:3] == ["ssh", "--", "pinky@robot"]
    assert "shadow.previous" in runner.calls[0][-1]
    runner = FakeRunner(stdout="shadow: /var/lib/rosy/models/x\n")
    assert deliver.main(["status", "robot"], runner=runner) == 0
    assert "cat" in runner.calls[0][-1]


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
        rc = deliver.main(argv, runner=runner)
    except SystemExit as exc:  # argparse refusing an option-looking host is fine too
        rc = exc.code
    assert rc != 0
    assert runner.calls == []


def test_ssh_and_scp_end_options_before_targets(tmp_path):
    models = tmp_path / "models"
    rev = _model(models, "pass")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(models)], runner=runner) == 0
    assert runner.calls[0][:3] == ["ssh", "--", "pinky@robot"]
    assert runner.calls[1][:3] == ["scp", "-r", "--"]


# --- the generated push script, executed for real -------------------------------------------

def _bash_env():
    """(bash, to_posix) for a bash with sha256sum, else None. Git Bash needs cygpath for paths."""
    bash = shutil.which("bash")
    if not bash:
        return None
    probe = subprocess.run([bash, "-c", "command -v sha256sum"], capture_output=True, text=True)
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
        pytest.skip("needs bash with sha256sum (and cygpath on Windows)")
    bash, to_posix = env
    root = tmp_path / "models"
    root.mkdir()
    good = b"model-bytes"
    checks = [(hashlib.sha256(good).hexdigest(), "model.onnx")]

    def run(checks=checks):
        script = deliver.remote_script("push", REV, to_posix(root), checks=checks)
        return subprocess.run([bash, "-c", script], capture_output=True, text=True)

    def stage(content, folder):
        (root / folder).mkdir()
        (root / folder / "model.onnx").write_bytes(content)

    return root, to_posix, run, stage, good


def test_remote_script_fresh_install_sets_pointer(remote):
    root, to_posix, run, stage, good = remote
    stage(good, f"{REV}.partial")
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / REV / "model.onnx").read_bytes() == good
    assert not (root / f"{REV}.partial").exists()
    assert (root / "shadow").read_text() == f"{to_posix(root)}/{REV}"


def test_remote_script_replaces_corrupt_existing_rev(remote):
    root, to_posix, run, stage, good = remote
    stage(b"corrupt", REV)
    stage(good, f"{REV}.partial")
    r = run()
    assert r.returncode == 0, r.stderr
    assert (root / REV / "model.onnx").read_bytes() == good
    bad = list(root.glob(f"{REV}.bad.*"))
    assert len(bad) == 1 and (bad[0] / "model.onnx").read_bytes() == b"corrupt"
    assert (root / "shadow").read_text() == f"{to_posix(root)}/{REV}"


def test_remote_script_failing_checksum_leaves_pointer_untouched(remote):
    root, to_posix, run, stage, good = remote
    (root / "shadow").write_text("/old/model")
    stage(b"tampered", f"{REV}.partial")
    r = run()
    assert r.returncode != 0
    assert (root / "shadow").read_text() == "/old/model"
    assert not (root / "shadow.tmp").exists() and not (root / "shadow.previous").exists()
    assert not (root / REV).exists()
