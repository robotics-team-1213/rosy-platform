"""Only new protocol2 images own the privileged RAUC unit and root-only bus policy."""
import json

import pytest

from test_os_ab_root_configuration import _configurer
from test_os_factory_release import _device, FACTORY_ID
from test_os_frozen_firstboot import _prefix, _stage
from test_image_layer_sync import sync_mod


@pytest.mark.parametrize("protocol", [1, 2])
def test_os_service_is_frozen_and_installed_only_on_protocol2(tmp_path, monkeypatch, protocol):
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    slot = root / "etc/rosy/os-slot.json"
    slot.write_text(json.dumps(dict(json.loads(slot.read_text()), schema_version=protocol)))
    _stage(_prefix(root))
    _configurer().configure(root, FACTORY_ID)
    for source, target in {
        "rosy-os-rauc.service": "etc/systemd/system/rosy-os-rauc.service",
        "rosy-rauc-dbus.conf": "etc/dbus-1/system.d/90-rosy-rauc.conf",
    }.items():
        frozen = root / "opt/rosy/os-bootstrap/native-runtime" / source
        assert frozen.is_file()
        if protocol == 2:
            assert (root / target).read_bytes() == frozen.read_bytes()
        else:
            assert not (root / target).exists()
    assert (root / "opt/rosy/os-bootstrap/native-runtime/os_rauc_service.py").is_file()
    assert not (root / "etc/systemd/system/multi-user.target.wants/rosy-os-rauc.service").exists()


@pytest.mark.parametrize("target", ["etc/systemd/system/rosy-os-rauc.service",
    "etc/systemd/system/rosy-os-rauc.service.d/override.conf", "etc/dbus-1/system.d/90-rosy-rauc.conf"])
def test_application_backup_or_sync_cannot_write_os_daemon_namespaces(target):
    with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
        sync_mod.check_destination(target)
