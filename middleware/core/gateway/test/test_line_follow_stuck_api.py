"""D-407 console decision API, CORE wiring and config layering for the lane stuck recovery."""

from pathlib import Path

import pytest
import yaml

from core.bridge import observation
from core.services import _line_follow_config
from core_common.config import _deep_merge
from core_features.command.arbitration import Mode
from core_features.line_follow.manager import LineFollowMode, LineObservation

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
REPO = Path(__file__).resolve().parents[4]
DEFAULT = REPO / "contracts" / "foundation" / "config" / "rosy_default.yaml"
PINKY = REPO / "middleware" / "apps" / "device" / "pinky" / "profile" / "config" / "core.yaml"
URL = "/api/v1/line-follow/stuck/decision"


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _stuck(core_client, *, front=0.15):
    """A CORE with line-follow on and one open obstacle stuck (console linked)."""
    client, services = core_client()
    clock = {"t": 0.0}
    lf = services.line_follow
    lf.bind_clock(lambda: clock["t"])
    lf.bind_recovery(console_linked=lambda: True, calibration_active=lambda: False)
    assert client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                      headers=OPERATOR).status_code == 200
    t = 0.0
    while t < 5.5:
        lf.observe_clearance(front, received_at=t)
        lf.observe_body_points([(front, 0.0)], range_min=0.0, received_at=t)
        lf.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                   error=0.0, confidence=0.9), received_at=t, source_now=t)
        clock["t"] = t + 0.01
        lf.tick(clock["t"])
        t = round(t + 0.1, 6)
    services.state.set_line_follow(lf.status())
    return client, services, lf.status().stuck.stuck_id


def test_core_binds_the_recovery_inputs(core_client):
    _, services = core_client()
    providers = services.line_follow._recovery_providers
    assert set(providers) == {"console_linked", "calibration_active", "linear_ceiling",
                              "preview_seq"}
    assert providers["console_linked"]() is False            # FleetAgent not connected
    assert providers["calibration_active"]() is False
    assert providers["linear_ceiling"]() == services.safety.limits.manual_linear


def test_console_link_is_debounced_on_recent_hub_traffic(core_client):
    """D-419: a reconnect blip (socket down, hub heard within one heartbeat period + reply
    deadline + slack) still counts as linked, so it does not skip the operator wait."""
    import time
    _, services = core_client()
    linked = services.line_follow._recovery_providers["console_linked"]
    agent = services.fleet_agent
    agent.connected = False
    agent.last_rx = time.monotonic() - 1.0
    assert linked() is True
    agent.last_rx = time.monotonic() - agent.link_fresh_s - 0.5
    assert linked() is False
    agent.connected = True
    assert linked() is True


def test_stuck_is_in_the_line_follow_status(core_client):
    client, _, stuck_id = _stuck(core_client)
    body = client.get("/api/v1/line-follow", headers=VIEWER).json()
    assert body["stuck"]["stuck_id"] == stuck_id and body["stuck"]["phase"] == "ASKING"
    assert body["stuck"]["decisions"] == ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


def test_decision_requires_operator_and_a_matching_stuck_id(core_client):
    client, _, stuck_id = _stuck(core_client)
    assert client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"},
                       headers=VIEWER).status_code == 403
    assert client.post(URL, json={"stuck_id": stuck_id, "decision": "JUMP"},
                       headers=OPERATOR).status_code in (400, 422)
    late = client.post(URL, json={"stuck_id": "stuck-old", "decision": "WAIT"}, headers=OPERATOR)
    assert late.status_code == 409 and late.json()["error"]["code"] == "STUCK_ID_MISMATCH"
    wait = client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=OPERATOR)
    assert wait.status_code == 200 and wait.json()["outcome"] == "hold"
    assert wait.json()["stuck"]["phase"] == "WAITING_CONSOLE"


def test_resume_refused_inside_stop_distance(core_client):
    client, _, stuck_id = _stuck(core_client, front=0.15)
    refused = client.post(URL, json={"stuck_id": stuck_id, "decision": "RESUME"},
                          headers=OPERATOR)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "STUCK_DECISION_REFUSED"


def test_back_and_retry_refused_while_local_recovery_is_off(core_client):
    client, _, stuck_id = _stuck(core_client)
    refused = client.post(URL, json={"stuck_id": stuck_id, "decision": "BACK_AND_RETRY"},
                          headers=OPERATOR)
    assert refused.status_code == 409 and "local_recovery_disabled" in refused.text


@pytest.mark.parametrize("decision, mode", [("ABORT", Mode.IDLE), ("MANUAL", Mode.MANUAL)])
def test_abort_and_manual_turn_line_follow_off(core_client, decision, mode):
    client, services, stuck_id = _stuck(core_client)
    done = client.post(URL, json={"stuck_id": stuck_id, "decision": decision}, headers=OPERATOR)
    assert done.status_code == 200 and done.json()["mode"] == "OFF"
    assert services.line_follow.mode is LineFollowMode.OFF and services.modes.mode is mode
    assert services.command.select_output().linear == 0.0


def test_estop_closes_the_stuck_and_late_answers_are_refused(core_client):
    client, services, stuck_id = _stuck(core_client)
    services.safety.trigger_estop("test")
    assert services.line_follow.status().stuck is None
    late = client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=OPERATOR)
    assert late.status_code == 409


def test_packaged_default_plus_pinky_plus_old_overlay_parses():
    """New keys in the default layer must not collide with an overlay (docs/solutions 2026-10-02)."""
    merged = _deep_merge(_deep_merge(_yaml(DEFAULT), _yaml(PINKY)),
                         {"line_follow": {"obstacle_escalate_s": 4.0, "lidar_forward_deg": 181.0}})
    config = _line_follow_config(merged["line_follow"])
    assert config.recovery_local_enabled is False and config.recovery_ask_s == 15.0
    assert config.recovery_back_m == 0.08 and config.recovery_back_speed == 0.03
    assert config.recovery_rear_clear_m == 0.06 and config.recovery_max_attempts == 2
    assert config.body_geometry_known and config.body_rear_x_m == -0.076
    generic = _line_follow_config(_yaml(DEFAULT)["line_follow"])
    assert not generic.body_geometry_known                   # never backs off without URDF


def test_scan_bridge_feeds_self_masked_body_points():
    class LineFollow:
        config = _line_follow_config({"lidar_forward_deg": 180.0, "lidar_self_mask": [
            {"from_deg": 170, "to_deg": 180, "max_range_m": 0.2}]})
        body = None
        clearance = "unset"
        wants_body_points = True

        def observe_body_points(self, points, *, range_min, received_at):
            self.body = (points, range_min)

        def observe_clearance(self, distance, received_at=None):
            self.clearance = distance

    class Services:
        line_follow = LineFollow()
        loc_mission = None          # D-395 P2-7 mission (main) shares the scan

    n = 360
    ranges = [float("inf")] * n
    ranges[0] = 0.30                     # scan -180 deg = robot forward (mount 180)
    ranges[180] = 0.25                   # scan 0 deg = robot rear
    ranges[175] = 0.18                   # scan -5 deg = robot +175 deg, inside the self-mask
    sample = {"ranges": ranges, "angle_min": -3.14159265, "angle_max": 3.14159265 * (n - 2) / n,
              "range_min": 0.15, "range_max": 12.0}
    services = Services()
    observation.front_clearance(services, sample, received_at=1.0)
    points, range_min = services.line_follow.body
    assert range_min == 0.15 and len(points) == 2
    assert min(x for x, _ in points) == pytest.approx(-0.25, abs=1e-3)
    assert services.line_follow.clearance == pytest.approx(0.30, abs=1e-3)

    services.line_follow.body = None
    del sample["range_min"]                  # review M2: missing range_min -> unknown blind band
    observation.front_clearance(services, sample, received_at=1.1)
    assert services.line_follow.body[1] is None
    services.line_follow.wants_body_points = False   # review L6: sector mode, nothing stuck
    services.line_follow.body = None
    observation.front_clearance(services, sample, received_at=1.2)
    assert services.line_follow.body is None and services.line_follow.clearance is not None


def test_manager_wants_body_points_only_near_a_stuck():
    from core_features.line_follow.manager import LineFollowConfig, LineFollowManager

    class Bus:
        def publish(self, *a, **k):
            pass

    m = LineFollowManager(Bus(), config=LineFollowConfig(), clock=lambda: 0.0)
    assert not m.wants_body_points                      # OFF
    m.set_mode(LineFollowMode.CAMERA_LINE)
    assert m.wants_body_points                          # waiting for a lane (loss timer runs)
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=0.0, visible=True,
                              error=0.0, confidence=0.9), received_at=0.0, source_now=0.0)
    m.observe_clearance(1.0, received_at=0.0)
    m.tick(0.01)
    assert not m.wants_body_points                      # tracking, nothing near


def test_manual_answer_respects_the_calibration_lease_and_cancels_navigation(core_client):
    """Review M3: MANUAL goes through the POST /mode rules (lease, nav/swarm cancel)."""
    client, services, stuck_id = _stuck(core_client)
    services.calibration.start(kind="lidar", label="other", ttl_s=30, owner_id="someone-else",
                               owner_role="operator")
    refused = client.post(URL, json={"stuck_id": stuck_id, "decision": "MANUAL"},
                          headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert services.line_follow.status().stuck.stuck_id == stuck_id      # not consumed

    client2, services2, stuck2 = _stuck(core_client)
    cancels = []
    original = services2.nav.cancel
    services2.nav.cancel = lambda source=None: (cancels.append(source), original(source=source))
    done = client2.post(URL, json={"stuck_id": stuck2, "decision": "MANUAL"}, headers=OPERATOR)
    assert done.status_code == 200 and services2.modes.mode is Mode.MANUAL
    assert cancels and cancels[-1].startswith("mode:")


def test_answer_audit_records_the_token(core_client):
    """Review L2: the answered event names the token, not only the role."""
    client, services, stuck_id = _stuck(core_client)
    seen = []
    services.events.subscribe(lambda event: seen.append(event))
    client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=OPERATOR)
    answered = [e for e in seen if e.type == "nav.line_stuck_answered"]
    assert answered and answered[0].data["by"] == "operator"
    ref = answered[0].data["principal_ref"]
    assert ref and "token_id" not in answered[0].data
    # The dev operator token has no configured id: its record id is digest[:12], an unsalted
    # hash prefix. The event names it by a per-process HMAC instead (review L4).
    from core_api_web.api.deps import token_digest
    assert ref.startswith("anon-") and token_digest("rosy-dev-operator")[:12] not in ref


def test_answered_event_passes_the_fleet_audit_filter(core_client):
    """D-407 re-run B: Fleet's event store refused `token_id` as a credential key."""
    import sys
    fleet_root = str(REPO / "operations" / "fleet")
    if fleet_root not in sys.path:
        sys.path.insert(0, fleet_root)
    module = pytest.importorskip("fleet.server.core_event_store")
    client, services, stuck_id = _stuck(core_client)
    seen = []
    services.events.subscribe(lambda event: seen.append(event))
    client.post(URL, json={"stuck_id": "stuck-old", "decision": "WAIT"}, headers=OPERATOR)
    client.post(URL, json={"stuck_id": stuck_id, "decision": "BACK_AND_RETRY"}, headers=OPERATOR)
    client.post(URL, json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=OPERATOR)
    stuck_events = [e for e in seen if e.type.startswith("nav.line_stuck_")]
    assert stuck_events
    for event in stuck_events:
        assert not module._contains_sensitive_field(event.model_dump(mode="json")), event.type


def test_recovery_overlay_types_coerce_or_fail_clearly():
    """Review L5: 2.0 attempts is 2; a quoted "true" is refused with the key named."""
    assert _line_follow_config({"recovery_max_attempts": 2.0}).recovery_max_attempts == 2
    assert _line_follow_config({"recovery_local_enabled": True}).recovery_local_enabled is True
    with pytest.raises(ValueError, match="recovery_local_enabled must be true or false"):
        _line_follow_config({"recovery_local_enabled": "true"})
    with pytest.raises(ValueError, match="recovery_max_attempts must be a whole number"):
        _line_follow_config({"recovery_max_attempts": 1.5})
    with pytest.raises(ValueError, match="recovery_max_attempts must be a whole number"):
        _line_follow_config({"recovery_max_attempts": "2"})


def test_principal_ref_keeps_configured_ids_and_hides_hash_prefix_ids():
    """Review L4: a configured id is a name; a digest-prefix id is replaced by a keyed ref."""
    from core_api_web.api.deps import principal_ref, token_digest
    digest = token_digest("some-secret-token")
    assert principal_ref({"id": "site-console", "digest": digest}) == "site-console"
    anon = principal_ref({"id": digest[:12], "digest": digest})
    assert anon.startswith("anon-") and digest[:12] not in anon
    assert principal_ref({"id": digest[:12], "digest": digest}) == anon     # stable in a run
