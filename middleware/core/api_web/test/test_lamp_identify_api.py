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
