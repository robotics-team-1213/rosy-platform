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
         "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import signing; "
         "assert signing.parse_sha256sums(b'')[0] == {}; "
         "entries,rejections=signing.verify_release_checksums(Path('.'),Path('unused.pem')); "
         "assert entries == {} and rejections[0].code == 'SHA256SUMS_MISSING'; "
         "assert signing.SIGNATURE_LENGTH == 64", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_dynamic_legacy_loader_can_use_its_original_module_object():
    import importlib.util
    import signing

    spec = importlib.util.spec_from_file_location(
        "dynamic_legacy_signing", ROOT / "deploy/robot/pinky_pro/release/signing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.verify_release_files is signing.verify_release_files
    assert module.verify_release_checksums is signing.verify_release_checksums
    assert module.SigningToolMissing is signing.SigningToolMissing
