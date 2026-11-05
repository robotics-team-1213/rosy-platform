"""Publication-only OS automation: immutable build identity and no device authority."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def module():
    spec = importlib.util.spec_from_file_location("robot_cd_os", ROOT / "tools/release/robot_cd_os.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(**changes):
    return dict(id=11, workflow_id=9, head_sha=SHA, head_branch="payload-reserved-2026.11.05-100",
                event="workflow_dispatch", status="completed", conclusion="success",
                repository={"id": 7}, head_repository={"id": 7}, **changes)


@pytest.mark.parametrize("field,value", [("head_sha", "b" * 40), ("head_branch", "main"),
    ("workflow_id", 10), ("event", "push"), ("repository", {"id": 8}),
    ("head_repository", {"id": 8}), ("conclusion", "failure"), ("status", "in_progress")])
def test_image_build_must_match_exact_reserved_source_and_workflow(field, value):
    helper = module()
    candidate = run()
    candidate[field] = value
    assert not helper.approved_image_run(candidate, sha=SHA, ref=run()["head_branch"], repo_id=7, workflow_id=9)


def test_image_build_accepts_only_exact_identity():
    assert module().approved_image_run(run(), sha=SHA, ref=run()["head_branch"], repo_id=7, workflow_id=9)


def test_publication_only_rollout_defers_every_device():
    from tools.release.prepare_os_release import _policy
    from os_update_rollout import authorize
    policy = _policy("2026.11.05-100", "b" * 64, [])
    assert policy["canary"] == [] and policy["canary_ok"] is False
    for hostname in ("rosy_42", "rosy_45", "rosy_46", "future-robot"):
        with pytest.raises(ValueError, match="DEFERRED"):
            authorize(policy, hostname, now=datetime(2099, 1, 1, tzinfo=timezone.utc))
