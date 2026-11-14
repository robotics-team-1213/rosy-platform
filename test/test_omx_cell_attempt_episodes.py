"""Attempt rows name their recorded episode; the read-only intake joins them and reports what is missing."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_attempt_episodes as cae  # noqa: E402
import cell_attempts  # noqa: E402
import cell_auto_safety  # noqa: E402
import episode_recorder as er  # noqa: E402

TRIED = {"locate": {"found": False}}


class Cell:
    """Answers `episode ...` like the runner does, through the real Recorder."""

    def __init__(self):
        self.recorder = er.Recorder()

    def act(self, command):
        words = command.split()[1:]
        return {"ok": True, **self.recorder.command(words)}


def carry(tmp_path, config, name_ok=True):
    cell = Cell()
    ep = cell_auto_safety.open_episode(cell, config, "A", "B", "box")
    cell.recorder.tick([0.0] * 6, [1.0] * 6)
    cell.act("episode save" if name_ok else "episode fail slipped")
    return cell_attempts.record({}, {}, "A", "B", 0, dict(TRIED), 0.0), ep


def setup(tmp_path):
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1")
    return {"episodes": {"root": str(tmp_path / "eps"), "cameras": {}}}


def test_record_names_the_episode_the_recorder_wrote(tmp_path):
    config = setup(tmp_path)
    attempt_id, _ = carry(tmp_path, config)
    row = cell_attempts.json.loads((tmp_path / "attempts.jsonl").read_text())
    folder = next((tmp_path / "eps").iterdir())
    assert row["episode"] == cae.episode_ref(folder) and row["episode"]["sha"]
    assert json.loads((folder / "task.json").read_text())["attempt_id"] == attempt_id == row["attempt_id"]


def test_intake_joins_by_row_and_by_task_json_and_never_writes(tmp_path):
    config = setup(tmp_path)
    carry(tmp_path, config)
    rows = cae.load_rows(tmp_path / "attempts.jsonl")
    before = sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file())
    out = cae.join(rows, tmp_path / "eps")
    legacy = {k: v for k, v in rows[0].items() if k != "episode"}  # a row before the field
    out_legacy = cae.join([legacy], tmp_path / "eps")
    assert out["counts"] == {"ok": 1} and out_legacy["counts"] == {"ok": 1}
    assert out_legacy["joined"][0]["episode"]["id"] == rows[0]["episode"]["id"]
    assert before == sorted((p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file())


def test_missing_changed_and_unlinked_are_reported(tmp_path):
    config = setup(tmp_path)
    carry(tmp_path, config)
    row = cae.load_rows(tmp_path / "attempts.jsonl")[0]
    folder = Path(row["episode"]["path"])
    (folder / "result.json").write_text("{}")
    assert cae.join([row], tmp_path / "eps")["counts"] == {"sha_changed": 1}
    gone = dict(row, episode={**row["episode"], "path": str(tmp_path / "x"), "id": "x"})
    assert cae.join([gone], tmp_path / "eps")["counts"] == {"missing_folder": 1, "unlinked": 1}
    plain = {"attempt_id": "other-001", "outcome": "failed"}  # old row, no episode anywhere
    assert cae.join([plain])["joined"][0]["status"] == "no_episode"


def test_old_rows_without_the_field_still_load_and_summarise(tmp_path):
    old = {"schema": cell_attempts.SCHEMA, "attempt_id": "old-001", "from": "A", "to": "B", "outcome": "placed",
           "fail_stage": None, "fail_class": None, "locate": {"found": True, "arm_m": [0.1, 0.2]}}
    path = tmp_path / "attempts.jsonl"
    path.write_text(json.dumps(old) + "\n")
    rows = cae.load_rows(path)
    assert cell_attempts.summary(rows)["placed"] == 1
    assert "episode" not in rows[0] and cae.join(rows)["counts"] == {"no_episode": 1}


def test_no_episodes_configured_leaves_a_null_reference(tmp_path):
    cell_attempts.start(tmp_path / "attempts.jsonl", "r2")
    cell_auto_safety.open_episode(Cell(), {}, "A", "B", "box")
    cell_attempts.record({}, {}, "A", "B", 0, dict(TRIED), 0.0)
    assert cae.load_rows(tmp_path / "attempts.jsonl")[0]["episode"] is None
