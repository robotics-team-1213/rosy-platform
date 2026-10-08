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
    monkeypatch.setattr(host_hardware, "_last_test", {})
    configured = robot("rosy_26", {"lamp_identify": {"color": "amber"}})
    assert host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, configured)["color"] == "amber"
    for unset in (robot("rosy_99"), robot("rosy_26", {"lamp_identify": {"color": "red"}})):
        monkeypatch.setattr(host_hardware, "_last_test", {})
        with pytest.raises(ApiError):
            host_hardware.host_lamp_identify(LampIdentifyRequest(), auth, unset)
    assert [json.loads(w[1])["action"] for w in writes] == ["identify_blue", "identify_amber", "identify_amber"]
