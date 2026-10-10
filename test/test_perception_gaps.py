"""Contracts for the perception blind-spot registry (tools/harness/perception_gaps.yaml)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

import perception_gaps
import rosy_harness as harness

ROOT = Path(__file__).resolve().parents[1]
KNOWN_ADRS = {"D-491"}

GOOD_ROW = {
    "id": "P-01",
    "kind": "miss",
    "spot": "the model labels only the near floor",
    "born": "20261009T073835Z",
    "evidence": ["src/launch.py:2", "D-491"],
    "replay": "src/launch.py",
    "owner": "perception",
    "status": "OPEN",
    "next": "replay the same recording before closing",
}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "launch.py").write_text("a\nb\nc\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("measured\n", encoding="utf-8")
    return tmp_path


def _errors(repo: Path, *rows: dict) -> list[str]:
    errors, _ = perception_gaps.validate({"spots": list(rows)}, repo, KNOWN_ADRS)
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
    closed = _row(id="P-02", status="CLOSED", validated_by="docs/note.md")
    hold = _row(id="P-03", kind="candidate", status="HOLD", replay="unbuilt", born="docs/note.md")
    device = _row(id="P-04", born="device:2026-10-10", replay="unbuilt")
    assert _errors(repo, _row(), closed, hold, device) == []


def test_registry_must_list_spots(repo):
    errors, _ = perception_gaps.validate({"spots": "nope"}, repo, KNOWN_ADRS)
    assert errors == ["spots must be a list"]


def test_wrong_schema_is_an_error(repo):
    errors, _ = perception_gaps.validate({"schema": "rosy.other.v1", "spots": [_row()]}, repo, KNOWN_ADRS)
    assert any("schema" in e for e in errors)


@pytest.mark.parametrize("field", perception_gaps.REQUIRED)
def test_each_required_field_is_enforced(repo, field):
    assert any(f"missing field: {field}" in e for e in _errors(repo, _row(**{field: None})))


@pytest.mark.parametrize("spot_id", ["P-1", "p-01", "P-001", "G-01"])
def test_id_must_match_the_pattern(repo, spot_id):
    assert any("malformed id" in e for e in _errors(repo, _row(id=spot_id)))


def test_duplicate_id_is_an_error(repo):
    assert any("duplicate id" in e for e in _errors(repo, _row(), _row()))


@pytest.mark.parametrize("kind", ["sensor", "MISS", ""])
def test_unknown_kind_is_an_error(repo, kind):
    assert any("kind" in e for e in _errors(repo, _row(kind=kind or None)))


def test_candidate_cannot_look_adopted(repo):
    assert any("candidate status" in e for e in _errors(repo, _row(kind="candidate", status="OPEN")))
    assert any("candidate status" in e for e in _errors(repo, _row(kind="candidate", status="IN-PROGRESS")))
    assert _errors(repo, _row(kind="candidate", status="HOLD")) == []


@pytest.mark.parametrize("born", ["20261009", "device:2026-13-40", "note.md", "../docs/note.md"])
def test_born_must_name_a_recording_a_device_read_or_a_note(repo, born):
    assert _errors(repo, _row(born=born))


def test_unbuilt_replay_cannot_close_a_row(repo):
    assert any("unbuilt" in e for e in _errors(repo, _row(status="CLOSED", replay="unbuilt", validated_by="docs/note.md")))
    assert _errors(repo, _row(replay="unbuilt")) == []


def test_missing_replay_file_is_an_error(repo):
    assert any("replay not found" in e for e in _errors(repo, _row(replay="src/gone.py")))


def test_closed_row_needs_validated_by(repo):
    assert any("CLOSED requires validated_by" in e for e in _errors(repo, _row(status="CLOSED")))


def test_evidence_reuses_the_sim2real_path_check(repo):
    assert any("not found: src/gone.py" in e for e in _errors(repo, _row(evidence=["src/gone.py"])))
    assert any("unknown ADR: D-999" in e for e in _errors(repo, _row(evidence=["D-999"])))


@pytest.mark.parametrize("registry", [["not", "a", "mapping"], "text", None])
def test_non_mapping_registry_is_an_error_not_a_crash(repo, registry):
    errors, _ = perception_gaps.validate(registry, repo, KNOWN_ADRS)
    assert errors
    perception_gaps.render(registry)


def test_yaml_syntax_error_is_a_lint_error(tmp_path):
    harness_dir = tmp_path / "tools" / "harness"
    harness_dir.mkdir(parents=True)
    (harness_dir / "harness.yaml").write_text(
        "adr_log: log.md\nstatus: STATUS.md\nmodules: []\n"
        "perception_gaps: gaps.yaml\nperception_table: gaps.md\n", encoding="utf-8")
    (tmp_path / "log.md").write_text("# log\n", encoding="utf-8")
    (tmp_path / "gaps.yaml").write_text("spots: [\n  - id: P-01\n", encoding="utf-8")
    errors, _ = harness.lint(tmp_path)
    assert any(e.startswith("perception: cannot read gaps.yaml") for e in errors)


def test_repository_registry_is_clean_and_rendered():
    config = harness.load_config(ROOT)
    adr = harness.parse_adr_log((ROOT / config["adr_log"]).read_text(encoding="utf-8"), ROOT / "docs" / "adr")
    data = yaml.safe_load((ROOT / config["perception_gaps"]).read_text(encoding="utf-8"))
    errors, _ = perception_gaps.validate(data, ROOT, set(adr.index))
    assert errors == []
    table = (ROOT / config["perception_table"]).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert table == perception_gaps.render(data)
