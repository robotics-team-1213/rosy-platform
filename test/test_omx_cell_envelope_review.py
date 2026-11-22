"""D-911: the one-step review command records a human review without changing any rule."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_envelope_review as rev  # noqa: E402
from cell_envelope import SCHEMA, digest  # noqa: E402


def _ledger(tmp_path, scope="hardware", trials=3, placed=3):
    rows = []
    for i in range(trials):
        ok = i < placed
        rows.append({"attempt_id": f"a{i}", "outcome": "placed" if ok else "failed", "verify": {"verified": ok, "inside": ok},
                     "transfer": {"result": "placed" if ok else "contact"},
                     "envelope": {"task_sha256": "task-1", "mode": "commissioning", "scope": scope, "status": "commissioning"}})
    path = tmp_path / "attempts.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    env = tmp_path / "envelope.json"
    env.write_text(json.dumps({"schema": SCHEMA, "attempts_path": "attempts.jsonl", "reviews": []}), encoding="utf-8")
    return path, env, rows


def _add(path, env, **over):
    kw = dict(task_sha256="task-1", reviewed_by="Kim Reviewer", evidence_ref="lift and hold checked 2026-11-20", min_attempts=3,
              min_success_rate=1.0, home_tolerance_units=2.0, confirmed=True)
    return rev.add_review(path, env, **{**kw, **over})


def test_the_review_copies_the_key_scope_and_digest_from_the_ledger_and_the_human_fields_from_the_reviewer(tmp_path):
    path, env, rows = _ledger(tmp_path)
    review = _add(path, env)
    saved = json.loads(env.read_text(encoding="utf-8"))["reviews"]
    assert saved == [review] and review["scope"] == "hardware"
    assert review["attempts_sha256"] == digest(rows) and review["reviewed_by"] == "Kim Reviewer"
    assert (review["min_attempts"], review["min_success_rate"], review["home_tolerance_units"]) == (3, 1.0, 2.0)


@pytest.mark.parametrize("over, why", [
    ({"confirmed": False}, "confirm"), ({"reviewed_by": " "}, "required"), ({"evidence_ref": ""}, "required"),
    ({"min_attempts": 0}, "min_attempts"), ({"min_success_rate": 1.5}, "min_attempts"), ({"home_tolerance_units": 0}, "min_attempts"),
    ({"task_sha256": "other"}, "no such task"), ({"min_attempts": 4}, "do not meet"),
])
def test_nothing_is_recorded_without_the_human_fields_or_when_the_numbers_are_not_met(tmp_path, over, why):
    path, env, _ = _ledger(tmp_path)
    before = env.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=why):
        _add(path, env, **over)
    assert env.read_text(encoding="utf-8") == before


def test_simulation_trials_and_duplicates_are_refused(tmp_path):
    path, env, _ = _ledger(tmp_path, scope="simulation")
    with pytest.raises(ValueError, match="only a hardware task"):
        _add(path, env)
    path, env, _ = _ledger(tmp_path)
    _add(path, env)
    with pytest.raises(ValueError, match="duplicate"):
        _add(path, env)
    path2, env2, _ = _ledger(tmp_path, trials=3, placed=2)
    with pytest.raises(ValueError, match="do not meet"):
        _add(path2, env2)  # a failure stays in the denominator: 2/3 is not 100 %


def test_the_command_line_needs_every_human_field_and_prints_what_it_recorded(tmp_path, capsys):
    path, env, _ = _ledger(tmp_path)
    base = ["add", "--attempts", str(path), "--envelope", str(env), "--task-sha256", "task-1"]
    with pytest.raises(SystemExit):
        rev.main(base)  # no reviewer, evidence or numbers: no defaults exist
    full = base + ["--reviewed-by", "Kim", "--evidence-ref", "checked", "--min-attempts", "3", "--min-success-rate", "1.0",
                   "--home-tolerance", "2.0"]
    assert rev.main(full) == 2  # without --confirm-physical-review
    assert rev.main(full + ["--confirm-physical-review"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["recorded"]["reviewed_by"] == "Kim"
    assert rev.main(["list", str(path)]) == 0
