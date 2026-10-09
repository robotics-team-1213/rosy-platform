"""D-558 drivable model version ledger."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
_MODEL = ROOT / "learning" / "training" / "perception" / "model"
if str(_MODEL) not in sys.path:
    sys.path.insert(0, str(_MODEL))

import drivable_versions as dv  # noqa: E402

REV = "v13-drivable-20261010-aaaaaaaa"


def test_repo_ledger_holds_the_rejected_first_candidate():
    (first,) = [e for e in dv.load() if e["version"] == "v13.0.00"]
    assert first["revision"] == "v13-drivable-20261009-982b09a9" and first["status"] == "rejected"
    assert first["onnx_sha256"].startswith("982b09a9")


def test_saved_ledger_is_byte_identical_to_the_repo_file(tmp_path):
    dv.save(dv.load(), tmp_path / "l.yaml")
    assert (tmp_path / "l.yaml").read_bytes() == dv.LEDGER.read_bytes()


@pytest.mark.parametrize("version", ["v13.1.0", "13.1.00", "v13.1.100", "v13.x.00", None, 13])
def test_version_format(version):
    assert dv.version_error(version, REV)


def test_major_must_match_lineage():
    assert dv.version_error("v13.1.00", REV) is None
    assert "major 12" in dv.version_error("v12.1.00", REV)


def test_intake_error_cases(tmp_path):
    ledger = tmp_path / "l.yaml"
    dv.save([], ledger)
    assert "needs model_version" in dv.intake_error({"model_revision": REV}, ledger)
    assert dv.intake_error({"model_revision": REV, "model_version": "v13.1.00"}, ledger) is None
    assert dv.main(["--ledger", str(ledger), "add", "v13.1.00", "v13-drivable-20261010-bbbbbbbb",
                    "--onnx-sha256", "b" * 64, "--dataset", "d@" + "c" * 64,
                    "--rule", "D-554 1-9", "--note", "first"]) == 0
    assert "one version, one revision" in dv.intake_error(
        {"model_revision": REV, "model_version": "v13.1.00"}, ledger)
    assert dv.intake_error({"model_revision": "v13-drivable-20261010-bbbbbbbb",
                            "model_version": "v13.1.00"}, ledger) is None


def test_cli_refuses_duplicates_and_changes_status(tmp_path, capsys):
    ledger = tmp_path / "l.yaml"
    dv.save(dv.load(), ledger)
    base = ["--ledger", str(ledger)]
    dup = [*base, "add", "v13.0.00", "v13-drivable-20261010-cccccccc", "--onnx-sha256", "c" * 64,
           "--dataset", "d", "--rule", "r", "--note", "n"]
    assert dv.main(dup) == 2 and "duplicate version" in capsys.readouterr().err
    assert dv.main([*base, "set-status", "v13.0.00", "retired"]) == 0
    assert dv.load(ledger)[0]["status"] == "retired"
    assert dv.main([*base, "set-status", "v13.9.00", "retired"]) == 2
    assert dv.main([*base, "show", "v13.0.00"]) == 0
    assert "v13-drivable-20261009-982b09a9" in capsys.readouterr().out
