import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import LampIdentifyRequest
from core_api_web.api.errors import ApiError
from core_api_web.api.v1 import host_hardware


def test_lamp_identify_accepts_only_named_colors_and_writes_no_motion_command(monkeypatch, tmp_path):
    path = str(tmp_path / "identify.request")
    writes = []
    monkeypatch.setattr(host_hardware, "_test_paths", lambda _svc: (path, "result", "confirm"))
    monkeypatch.setattr(host_hardware, "_write_private", lambda *args: writes.append(args))
    auth = SimpleNamespace(token_id="operator-test")
    result = host_hardware.host_lamp_identify(LampIdentifyRequest(color="blue"), auth, object())
    assert result["state"] == "pending_visual_confirmation"
    assert json.loads(writes[0][1])["action"] == "identify_blue"
    assert "cmd_vel" not in writes[0][1]
    with pytest.raises(ApiError):
        host_hardware.host_lamp_identify(LampIdentifyRequest(color="amber"), auth, object())
    with pytest.raises(ValidationError):
        LampIdentifyRequest(color="red")


def test_a_quiet_identify_asks_the_face_for_the_silent_blink(monkeypatch, tmp_path):
    """D-596: Fleet's automatic requests carry quiet; the face blinks without the call chirp."""
    writes = []
    monkeypatch.setattr(host_hardware, "_test_paths", lambda _svc: (str(tmp_path / "q"), "r", "c"))
    monkeypatch.setattr(host_hardware, "_write_private", lambda *args: writes.append(args))
    result = host_hardware.host_lamp_identify(LampIdentifyRequest(color="blue"),
                                              SimpleNamespace(token_id="fleet"), object(), quiet=True)
    assert result["color"] == "blue"
    assert json.loads(writes[0][1])["action"] == "identify_blue_quiet"
    assert "identify_blue_quiet" in host_hardware.HW_TEST_ACTIONS


def test_lamp_identify_without_a_color_uses_the_robot_s_configured_colour(monkeypatch, tmp_path):
    writes = []
    monkeypatch.setattr(host_hardware, "_test_paths", lambda _svc: (str(tmp_path / "a"), "r", "c"))
    monkeypatch.setattr(host_hardware, "_write_private", lambda *args: writes.append(args))
    monkeypatch.setattr(host_hardware, "_last_test", {})
    auth = SimpleNamespace(token_id="operator-test")
    robot = lambda rid, config=None: SimpleNamespace(identity=SimpleNamespace(robot_id=rid), config=config)
    # D-472 4 defaults: rosy_26 blue, rosy_60 amber (orange).
    assert host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, robot("rosy_26"))["color"] == "blue"
    monkeypatch.setattr(host_hardware, "_last_test", {})
    assert host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, robot("rosy_60"))["color"] == "amber"
    # D-562 renumbered ids keep the same colours: 9dfk rosy_41 blue, 8kcn rosy_40 amber.
    for rid, colour in (("rosy_41", "blue"), ("rosy_40", "amber")):
        monkeypatch.setattr(host_hardware, "_last_test", {})
        assert host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, robot(rid))["color"] == colour
    monkeypatch.setattr(host_hardware, "_last_test", {})
    configured = robot("rosy_26", {"lamp_identify": {"color": "amber"}})
    assert host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, configured)["color"] == "amber"
    for unset in (robot("rosy_99"), robot("rosy_26", {"lamp_identify": {"color": "red"}})):
        monkeypatch.setattr(host_hardware, "_last_test", {})
        with pytest.raises(ApiError):
            host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, unset)
    assert [json.loads(w[1])["action"] for w in writes] == ["identify_blue", "identify_amber", "identify_blue", "identify_amber", "identify_amber"]


@pytest.mark.parametrize("answer, state, reason", [
    (None, "pending", None),
    ({"state": "done"}, "shown", None),
    ({"state": "failed", "reason": "CAUTION_ACTIVE"}, "refused", "CAUTION_ACTIVE"),
    ({"state": "failed"}, "refused", "FAILED"),                    # a payload before the reason
    ({"state": "unavailable", "reason": "no such thing"}, "refused", "UNAVAILABLE"),
])
def test_the_identify_result_says_shown_or_refused_with_the_face_reason(monkeypatch, tmp_path, answer, state, reason):
    """D-596 rev 2026-10-10: Fleet asks CORE whether rosy-face blinked or refused, and why."""
    result_path = tmp_path / "hw-test.json"
    monkeypatch.setattr(host_hardware, "_test_paths", lambda _svc: (str(tmp_path / "req"), str(result_path), "c"))
    monkeypatch.setattr(host_hardware, "_write_private", lambda *args: None)
    monkeypatch.setattr(host_hardware, "_last_test", {})
    monkeypatch.setattr(host_hardware, "_last_identify", {})
    auth = SimpleNamespace(token_id="fleet")
    started = host_hardware.host_lamp_identify(LampIdentifyRequest(color="blue"), auth, object())
    if answer is not None:
        result_path.write_text(json.dumps({"schema": 1, "request_id": started["request_id"], "action": "identify_blue",
                                           "detail": "x", "finished_at": "2026-10-10T00:00:00+00:00", **answer}),
                               encoding="utf-8")
    got = host_hardware.host_lamp_identify_result(started["request_id"], auth, object())
    assert (got["state"], got["reason"]) == (state, reason)
    with pytest.raises(ApiError) as unknown:
        host_hardware.host_lamp_identify_result("0" * 16, auth, object())
    assert unknown.value.http_status == 404


def test_an_unanswered_identify_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(host_hardware, "_test_paths", lambda _svc: (str(tmp_path / "req"), str(tmp_path / "none"), "c"))
    asked = host_hardware.time.monotonic() - host_hardware.IDENTIFY_RESULT_WAIT_S - 1
    monkeypatch.setattr(host_hardware, "_last_identify", {str(tmp_path / "req"): ("ab" * 8, asked)})
    got = host_hardware.host_lamp_identify_result("ab" * 8, SimpleNamespace(token_id="fleet"), object())
    assert got["state"] == "expired"
