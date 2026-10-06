"""Contracts for the sim2real gap registry (tools/harness/sim2real_gaps.yaml).

The registry is linted by ``rosy_harness.py lint`` so its rows cannot rot:
fields, tiers, statuses, ids, evidence paths and CLOSED validation records.
"""

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import rosy_harness as harness
import sim2real

ROOT = Path(__file__).resolve().parents[1]
KNOWN_ADRS = {"D-397"}

GOOD_ROW = {
    "id": "G-01",
    "gap": "sim camera pitch differs from the measured robot",
    "evidence": ["src/launch.py:2", "src/launch.py:1-2,3", "D-397"],
    "tier": ["M"],
    "owner": "gz_sim",
    "status": "OPEN",
    "next": "read the calibration store",
}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "launch.py").write_text("a\nb\nc\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "result.md").write_text("ok\n", encoding="utf-8")
    return tmp_path


def _errors(repo: Path, *rows: dict) -> list[str]:
    errors, _ = sim2real.validate({"gaps": list(rows)}, repo, KNOWN_ADRS)
    return errors


def _row(**changes) -> dict:
    row = copy.deepcopy(GOOD_ROW)
    for key, value in changes.items():
        if value is None:
            row.pop(key)
        else:
            row[key] = value
    return row


def test_valid_registry_has_no_errors(repo):
    closed = _row(id="G-02", status="CLOSED", tier=["R", "M"], validated_by="docs/result.md")
    assert _errors(repo, _row(), closed) == []


def test_registry_must_list_gaps(repo):
    errors, _ = sim2real.validate({"gaps": "nope"}, repo, KNOWN_ADRS)
    assert errors == ["gaps must be a list"]


@pytest.mark.parametrize("field", sim2real.SIM2REAL_REQUIRED)
def test_each_required_field_is_enforced(repo, field):
    assert any(f"missing field: {field}" in e for e in _errors(repo, _row(**{field: None})))


@pytest.mark.parametrize("tier", [["X"], [], "M", ["M", "M"]])
def test_tier_must_be_a_list_of_known_layers(repo, tier):
    assert any("tier" in e for e in _errors(repo, _row(tier=tier)))


def test_unknown_status_is_an_error(repo):
    assert any("status" in e for e in _errors(repo, _row(status="DONE")))


@pytest.mark.parametrize("gap_id", ["G-1", "g-01", "G-001", "X-01"])
def test_id_must_match_the_pattern(repo, gap_id):
    assert any("malformed id" in e for e in _errors(repo, _row(id=gap_id)))


def test_duplicate_id_is_an_error(repo):
    assert any("duplicate id" in e for e in _errors(repo, _row(), _row()))


def test_evidence_must_be_a_non_empty_list(repo):
    assert any("evidence" in e for e in _errors(repo, _row(evidence="src/launch.py")))
    assert any("evidence" in e for e in _errors(repo, _row(evidence=[])))


def test_missing_evidence_path_is_an_error(repo):
    assert any("not found: src/gone.py" in e for e in _errors(repo, _row(evidence=["src/gone.py"])))


def test_evidence_line_past_the_end_is_an_error(repo):
    assert any("line 9" in e for e in _errors(repo, _row(evidence=["src/launch.py:2-9"])))


def test_unknown_adr_is_an_error(repo):
    assert any("unknown ADR: D-999" in e for e in _errors(repo, _row(evidence=["D-999"])))


def test_closed_row_needs_validated_by(repo):
    assert any("CLOSED requires validated_by" in e for e in _errors(repo, _row(status="CLOSED")))


def test_closed_row_validation_path_must_exist(repo):
    row = _row(status="CLOSED", validated_by="docs/missing.md")
    assert any("not found: docs/missing.md" in e for e in _errors(repo, row))


def test_branch_only_evidence_is_checked_on_that_branch(repo):
    if shutil.which("git") is None:
        pytest.skip("needs git")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "harness@test")
    git("config", "user.name", "harness")
    git("add", "src/launch.py")
    git("commit", "-q", "-m", "base")
    git("branch", "docs/side")

    ok = _row(evidence=[{"path": "src/launch.py", "branch": "docs/side"}])
    assert _errors(repo, ok) == []
    gone = _row(evidence=[{"path": "docs/result.md", "branch": "docs/side"}])
    assert any("not found on docs/side: docs/result.md" in e for e in _errors(repo, gone))

    errors, warnings = sim2real.validate(
        {"gaps": [_row(evidence=[{"path": "x.md", "branch": "docs/landed"}])]}, repo, KNOWN_ADRS)
    assert errors == [] and any("docs/landed" in w for w in warnings)


def test_repository_registry_is_clean_and_rendered():
    config = harness.load_config(ROOT)
    adr = harness.parse_adr_log((ROOT / config["adr_log"]).read_text(encoding="utf-8"), ROOT / "docs" / "adr")
    data = yaml.safe_load((ROOT / config["sim2real_gaps"]).read_text(encoding="utf-8"))
    errors, _ = sim2real.validate(data, ROOT, set(adr.index))
    assert errors == []
    table = (ROOT / config["sim2real_table"]).read_text(encoding="utf-8")
    assert all(row["id"] in table for row in data["gaps"])
