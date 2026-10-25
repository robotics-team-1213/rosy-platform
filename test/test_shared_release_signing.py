"""Common release trust code must retain legacy imports and isolated installs."""

import importlib
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "deploy/hosts/common/release/signing.py"


def test_legacy_signing_import_is_the_common_module():
    import signing

    common = importlib.import_module("deploy.hosts.common.release.signing")
    assert signing is common
    assert Path(signing.__file__).resolve() == COMMON
    assert signing.SigningToolMissing is common.SigningToolMissing


def test_canonical_signing_runs_without_repository(tmp_path):
    destination = tmp_path / "signing.py"
    destination.write_bytes(COMMON.read_bytes())
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); import signing; "
         "assert signing.parse_sha256sums(b'')[0] == {}; "
         "assert signing.SIGNATURE_LENGTH == 64", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
