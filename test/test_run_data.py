"""Teleop checks and drive recordings stay in their own data folders."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import importlib.util

SPEC = importlib.util.spec_from_file_location("run_data", ROOT / "tools" / "run_data.py")
assert SPEC and SPEC.loader
run_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_data)


def _repo(tmp_path: Path) -> Path:
    for kind in run_data.KINDS:
        (tmp_path / "data" / kind).mkdir(parents=True)
    return tmp_path


def test_teleop_session_has_commands_and_drive_session_has_bags(tmp_path: Path):
    repo = _repo(tmp_path)
    when = datetime(2026, 9, 24, 1, 2, 3, tzinfo=timezone.utc)
    teleop = run_data.create_session(repo, "teleop", "forward_check", when=when)
    drive = run_data.create_session(repo, "drive", "map-loop", when=when)
    assert teleop.parent == repo / "data" / "teleop"
    assert (teleop / "commands.jsonl").is_file()
    assert not (teleop / "bags").exists()
    assert (drive / "trace.jsonl").is_file()
    assert (drive / "bags").is_dir()
    assert run_data.session_summary(teleop)["present"]["commands"] is True
    assert run_data.session_summary(drive)["present"]["bags"] is True


def test_list_keeps_the_two_kinds_apart(tmp_path: Path):
    repo = _repo(tmp_path)
    run_data.create_session(repo, "teleop", "look")
    run_data.create_session(repo, "drive", "run")
    assert len(run_data.list_sessions(repo, "teleop")) == 1
    assert len(run_data.list_sessions(repo, "drive")) == 1


def test_records_go_to_the_file_for_that_kind(tmp_path: Path):
    repo = _repo(tmp_path)
    teleop = run_data.create_session(repo, "teleop", "look")
    drive = run_data.create_session(repo, "drive", "run")
    run_data.append_record(teleop, {"linear": 0.1, "angular": 0.0})
    run_data.append_record(drive, {"x": 1.0, "y": 0.2})
    assert '"linear": 0.1' in (teleop / "commands.jsonl").read_text(encoding="utf-8")
    assert '"x": 1.0' in (drive / "trace.jsonl").read_text(encoding="utf-8")
    assert (drive / "commands.jsonl").exists() is False


def test_label_and_kind_cannot_leave_the_data_folders(tmp_path: Path):
    repo = _repo(tmp_path)
    with pytest.raises(run_data.RunDataError):
        run_data.create_session(repo, "teleop", "../secrets")
    with pytest.raises(run_data.RunDataError):
        run_data.create_session(repo, "bags", "loop")
