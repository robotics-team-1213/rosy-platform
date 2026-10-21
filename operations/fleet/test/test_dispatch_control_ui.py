from pathlib import Path


WEB = Path(__file__).resolve().parents[2] / 'site_ui' / 'console'


def test_dispatch_control_status_and_operator_rearm_are_wired():
    source = (WEB / "shared/console-refresh.js").read_text(encoding="utf-8")
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "createConsoleRefresh({" in (WEB / "console.js").read_text(encoding="utf-8")
    assert 'id="dispatch-control-title"' in index
    assert 'id="dispatch-control-detail"' in index
    assert 'id="dispatch-rearm"' in index
    assert '"/api/fleet/dispatch-control"' in source
    assert '"/api/fleet/dispatch/rearm"' in source
    assert 'expected_generation: state.generation' in source
    assert 'auth.role === "operator"' in source
    assert 'state.rearm_available' in source
