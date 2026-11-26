"""A closed dispatch latch alone is DISPATCH_REARM_REQUIRED, not HUMAN_HOLD; real hazards stay HUMAN_HOLD."""
import pytest

from fleet.server.trip_ports import TripError
from fleet.server.trip_runner import TripRunner


def _runner(state):
    r = object.__new__(TripRunner)
    r.human_hold_fn = lambda: state() is not None
    r.hold_state_fn = state
    return r


def test_restart_latch_reports_rearm_required():
    ctrl = {"dispatch_enabled": False, "reason": "PROCESS_RESTARTED", "rearm_available": True,
            "queued_tasks": 0, "unresolved_actions": 0}
    r = _runner(lambda: ("DISPATCH_REARM_REQUIRED", ctrl))
    with pytest.raises(TripError) as e:
        r._check_human_hold()
    assert e.value.code == "DISPATCH_REARM_REQUIRED" and e.value.detail["rearm_available"] is True


def test_real_hazard_stays_human_hold():
    r = _runner(lambda: ("HUMAN_HOLD", {}))
    with pytest.raises(TripError) as e:
        r._check_human_hold()
    assert e.value.code == "HUMAN_HOLD"


def test_route_fallback_wires_reason():
    """A runner built before install_pipeline_routes gets the reason from app.state, not a bare HUMAN_HOLD."""
    from types import SimpleNamespace
    from fleet.server.trip_routes import install_trip_routes
    app = SimpleNamespace(state=SimpleNamespace(pipeline_hold_state_fn=lambda: ("DISPATCH_REARM_REQUIRED", {}),
                                                pipeline_human_hold_fn=lambda: True))
    app.post = app.get = app.delete = lambda *a, **k: (lambda f: f)
    r = object.__new__(TripRunner)
    try:
        install_trip_routes(app, console=None, site_maps=None, routing_config=None, require_operator=None,
                            require_named_operator=None, caps_for=None, runner=r, read_guard=[])
    except Exception:
        pass  # route registration past the wiring is not under test
    with pytest.raises(TripError) as e:
        r._check_human_hold()
    assert e.value.code == "DISPATCH_REARM_REQUIRED"


def test_pipeline_dir_override(tmp_path, monkeypatch):
    """A sim host without /var/lib/rosy names a writable ledger dir instead of the fail-closed /tmp."""
    from fleet.server.sitemap.pipeline_routes import _storage_dir
    monkeypatch.setenv("ROSY_VAR_LIB", str(tmp_path))
    assert _storage_dir() == tmp_path / "pipeline" and (tmp_path / "pipeline").is_dir()
