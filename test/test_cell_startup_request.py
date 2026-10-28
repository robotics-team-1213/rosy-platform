"""Only an explicit simulator startup request may consume a canonical Fleet rearm."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))


def fixture(tmp_path, *, stale=False):
    from g2_startup_session import publish_json
    challenge = {"operation": "SIM_STARTUP_HOME", "nonce": "owner-nonce", "owner_session_id": "session",
                 "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01",
                 "profile_revision": "sim-profile", "target_sha256": "1" * 64}
    publish_json(tmp_path / "startup-awaiting-authorization.json", challenge)
    calls = []
    def request(method, path, body=None):
        calls.append((method, path, body))
        assert (tmp_path / "startup-rearm-intent.json").exists()
        assert not (tmp_path / "startup-request.json").exists()
        return {"dispatch_enabled": True, "authority_epoch": 3,
                "generation": 10 if stale and method == "GET" else 9}
    return NS(request=request, credentials={"site": {"approver": {"principal_id": "g2-sim-approver"}}}), calls


def test_no_startup_approval_never_rearms_or_publishes_request(tmp_path):
    from g2_runner import authorize_startup
    client, calls = fixture(tmp_path)
    with pytest.raises(PermissionError):
        authorize_startup(tmp_path, client, {"generation": 8, "dispatch_enabled": False}, approved=False)
    assert calls == [] and not (tmp_path / "startup-request.json").exists()


def test_request_binds_current_fleet_generation_and_is_never_replayed(tmp_path):
    from g2_runner import authorize_startup
    client, calls = fixture(tmp_path)
    control = {"generation": 8, "dispatch_enabled": False}
    authorize_startup(tmp_path, client, control, approved=True)
    assert calls[0] == ("POST", "/api/fleet/dispatch/rearm", {"expected_generation": 8})
    assert calls[1][:2] == ("GET", "/api/fleet/dispatch-control")
    request = json.loads((tmp_path / "startup-request.json").read_text())
    assert request["dispatch_generation"] == 9 and request["authority_epoch"] == 3
    assert request["nonce"] == "owner-nonce" and request["actor_id"] == "g2-sim-approver"
    with pytest.raises(FileExistsError):
        authorize_startup(tmp_path, client, control, approved=True)
    assert len(calls) == 2


def test_changed_generation_readback_never_authorizes_motion(tmp_path):
    from g2_runner import authorize_startup
    client, calls = fixture(tmp_path, stale=True)
    with pytest.raises(RuntimeError):
        authorize_startup(tmp_path, client, {"generation": 8, "dispatch_enabled": False}, approved=True)
    assert len(calls) == 2 and not (tmp_path / "startup-request.json").exists()


def test_run_needs_separate_startup_approval_before_isolation_or_children(tmp_path, monkeypatch):
    import g2_runner
    monkeypatch.setattr(sys, "argv", ["g2_runner", "--mode", "run", "--evidence", str(tmp_path / "run"),
                                     "--approve-isolated-simulation"])
    monkeypatch.setattr(g2_runner, "isolation_guard", lambda _: pytest.fail("must refuse before starting"))
    with pytest.raises(SystemExit) as error:
        g2_runner.main()
    assert error.value.code == 2 and not (tmp_path / "run").exists()
