"""A resident GPU process holds GPU jobs but not the non-GPU pilot collection jobs."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/site/rosy_model_code.py"


def module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("model_code_gpu_hold", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_non_gpu_jobs_are_known_entry_points():
    m = module()
    assert m.NON_GPU_JOBS and m.NON_GPU_JOBS <= set(m.JOB_ENTRY_POINTS)


@pytest.mark.skipif(os.name == "nt", reason="Linux work lock")
@pytest.mark.parametrize("script, held", [("dataset/pilot_review.py", False),
                                          ("dataset/fetch_http.py", False),
                                          ("rosy_ml.py", True)])
def test_gpu_probe_holds_only_gpu_jobs(tmp_path, monkeypatch, script, held):
    m = module()
    monkeypatch.setattr(m, "gpu_busy", lambda: "GPU compute job")
    monkeypatch.setattr(m, "legacy_busy", lambda roots: None)
    config = {"root": str(tmp_path), "key_id": "test", "public_key": str(tmp_path / "k.pub"),
              "python": sys.executable, "work_dir": str(tmp_path), "legacy_roots": [str(tmp_path)]}
    # No release is installed, so a job that passes the busy check fails later on something else.
    with pytest.raises(Exception) as caught:
        m.execute(config, script, [])
    assert isinstance(caught.value, m.WorkBusy) is held
