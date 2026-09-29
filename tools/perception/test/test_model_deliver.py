"""Task 9: model delivery to the robot (D-356)."""
import json
import shlex
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


def _model(models: Path, verdict: str) -> str:
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
    (models / rev / "intake_report.json").write_text(
        json.dumps({"model_revision": rev, "verdict": verdict}), encoding="utf-8")
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
    assert f"cp {root}/shadow {root}/shadow.previous" in s
    assert s.index(f"cp {root}/shadow {root}/shadow.previous") < swap


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
    assert runner.calls[0][:2] == ["ssh", "pinky@robot"]
    assert "shadow.previous" in runner.calls[0][-1]
    runner = FakeRunner(stdout="shadow: /var/lib/rosy/models/x\n")
    assert deliver.main(["status", "robot"], runner=runner) == 0
    assert "cat" in runner.calls[0][-1]
