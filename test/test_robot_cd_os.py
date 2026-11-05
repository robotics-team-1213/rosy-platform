"""Publication-only OS automation: immutable build identity and no device authority."""
import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def module():
    sys.path.insert(0, str(ROOT / "tools/release"))
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


class Coordinator:
    """One coordinator journal; no signing or network is used in these phases."""
    def __init__(self, tmp_path):
        self.config = {"repo_id": 7, "os_engineering": True}
        self.repo = "robotics-team-1213/rosy-platform"
        self.folder = tmp_path
        self.state = {"deployed_sha": "b" * 40, "delivery_base_sha": "b" * 40}
        self.calls, self.checkpoints = [], []
        self.candidate = run()

    def save(self, **values):
        self.state.update(values)
        self.checkpoints.append(json.loads(json.dumps(self.state)))

    def audit(self, result):
        return result

    def gh(self, *args):
        self.calls.append(args)
        assert self.state["phase"] == ("os_reserving" if "git/refs" in args[3] else "os_dispatching")

    def api(self, path):
        if path.startswith("git/matching-refs/"):
            return []
        if path == "actions/workflows/build-pinky-image.yml":
            return {"id": 9}
        if "/runs?" in path:
            return {"total_count": 1, "workflow_runs": [self.candidate]}
        if path == "actions/runs/11":
            return self.candidate
        raise AssertionError(path)


def test_dispatch_uses_reserved_tag_once_and_next_tick_only_observes(tmp_path):
    helper, c = module(), Coordinator(tmp_path)
    assert helper.advance(c, SHA, "success", "OS change") == "os_build_dispatched"
    ref = c.state["os_build_ref"]
    assert ref.startswith("payload-reserved-") and "os-pinky-pro" not in ref
    assert c.calls[-1][c.calls[-1].index("--ref") + 1] == ref
    c.candidate.update(head_branch=ref, status="in_progress", conclusion=None)
    assert helper.advance(c, SHA, "success") == "waiting_os_build"
    assert helper.advance(c, SHA, "success") == "waiting_os_build"
    assert len(c.calls) == 2  # one atomic ref and one dispatch
    assert c.state["build_run"] == 11


def test_pending_ci_cannot_reserve_build_or_sign(tmp_path):
    c = Coordinator(tmp_path)
    assert module().advance(c, SHA, "pending") == "waiting_os_ci"
    assert not c.calls and not c.checkpoints


def test_published_os_does_not_advance_either_device_baseline(tmp_path, monkeypatch):
    helper, c = module(), Coordinator(tmp_path)
    import tools.release.publish_os_release as publisher
    baseline = dict(c.state)
    c.state.update(sha=SHA, phase="os_publishing", release_id="2026.11.05-100", os_output="signed",
                   os_public_key="public", os_publication={"nonce": "a" * 32})

    def publish(*args, **kwargs):
        assert kwargs["publication_only"] is True and kwargs["apply"] is True
        kwargs["journal"]({"nonce": "a" * 32, "published": True})
        return {"applied": True}

    monkeypatch.setattr(publisher, "publish", publish)
    assert helper.advance(c, SHA, "success") == "os_published"
    assert c.state["phase"] == "done" and c.state["os_published_sha"] == SHA
    assert all(c.state[key] == value for key, value in baseline.items())


def test_unsigned_identity_mismatch_stops_before_key_signing(tmp_path):
    dist = tmp_path
    (dist / "os-bundle-inputs").mkdir()
    (dist / "manifest.json").write_text(json.dumps(dict(schema_version=2, release_id="2026.11.05-100",
        product="rosy-os", board="pinky_pro", architecture="arm64")))
    (dist / "build-provenance.json").write_text(json.dumps(dict(source_revision="b" * 40, architecture="aarch64")))
    (dist / "os-bundle-inputs/inputs.json").write_text(json.dumps(dict(source_revision=SHA, release_id="2026.11.05-100", boot_abi=2)))
    with pytest.raises(ValueError, match="approved build source"):
        module()._unsigned_identity(dist, "2026.11.05-100", SHA)
