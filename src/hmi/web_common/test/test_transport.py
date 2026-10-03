"""D-425 executable HTTP/scope contracts with the same Node runner as CI."""

from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("name", ["request.test.mjs", "scope.test.mjs", "page-scope.test.mjs"])
def test_transport_contracts(name, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(HERE / "transport" / name)],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    (tmp_path / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
