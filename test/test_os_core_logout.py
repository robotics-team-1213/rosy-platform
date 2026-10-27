"""Exercise the real CORE token writer/logout across the shared HOME boundary."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_os_first_boot_state import SERIAL, _provision_a


def test_core_logout_does_not_restore_a_browser_token_on_slot_return(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    for component in ("api", "services", "events"):
        monkeypatch.syspath_prepend(str(source / "middleware/core" / component))
    from core_api_web.api import deps
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1.auth import logout
    from core_common import config as config_owner

    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    monkeypatch.setenv("ROSY_DEPLOYMENT", "device")
    relative = "var/lib/rosy/core/.rosy/rosy.yaml"
    events = SimpleNamespace(publish=lambda *args, **kwargs: None)
    service = SimpleNamespace(config=yaml.safe_load((root_a / relative).read_text()), events=events)
    token = "fixture-browser-token-for-slot-logout"
    record = deps.new_token_record(token, "operator", source="pair-physical")
    monkeypatch.setattr(config_owner, "LOCAL_CONFIG_PATH", root_a / relative)
    deps.persist_token_records(service, deps.auth_entries(service.config) + [record])

    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    service.config = yaml.safe_load((root_b / relative).read_text())
    auth = deps.authenticate(service.config, "Bearer " + token, None)
    monkeypatch.setattr(config_owner, "LOCAL_CONFIG_PATH", root_b / relative)
    assert logout(auth, service).status_code == 204
    for root in (root_a, root_b):
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        loaded = yaml.safe_load((root / relative).read_text())
        with pytest.raises(ApiError) as refused:
            deps.authenticate(loaded, "Bearer " + token, None)
        assert refused.value.http_status == 401
        assert record["id"] not in {item["id"] for item in deps.auth_entries(loaded)}
