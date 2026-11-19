"""core_common.camera_quality and the deploy/robot/omx shim import without PYTHONPATH (cell PC units)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _run(code, cwd):
    return subprocess.run([sys.executable, '-I', '-c', code], cwd=cwd, capture_output=True, text=True, check=False)


def test_new_module_imports_with_foundation_only(tmp_path):
    code = (f"import sys; sys.path.insert(0, {str(REPO / 'contracts/foundation')!r}); "
            "from core_common.camera_quality import Readiness, POLICY; print(POLICY)")
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'omx-photometric-v3'


def test_flat_shim_imports_without_pythonpath_and_reexports(tmp_path):
    code = (f"import sys; sys.path.insert(0, {str(REPO / 'deploy/robot/omx')!r}); "
            "import camera_quality as c; from core_common import camera_quality as n; "
            "assert c.Readiness is n.Readiness and c.frame_quality is n.frame_quality; "
            "assert c.advancing_frame is n.advancing_frame and c.same_fresh_frame is n.same_fresh_frame; print('ok')")
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ok'
