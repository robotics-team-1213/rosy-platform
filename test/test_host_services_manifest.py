"""deploy/hosts/services.yaml: what tools/remote/update_status.py audits on each lab host."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = yaml.safe_load((ROOT / "deploy/hosts/services.yaml").read_text(encoding="utf-8"))["roles"]


def test_every_test_host_role_declares_the_storage_maintenance():
    # 2026-10-26: the site role lacked it, so the site PC had no cleanup and update_status never noticed.
    for role in ("model", "ai", "site"):
        units = ROLES[role]
        assert {"rosy-test-storage.service", "rosy-test-storage.timer"} <= set(units), role
        assert units["rosy-test-storage.timer"]["run"] == "timer", role


def test_native_omx_units_are_declared_once_separately_from_fleet_site_units():
    native = {name for units in ROLES.values() for name in units if name.startswith('rosy-omx-')}
    assert native and native == set(ROLES['omx'])
    assert not (native & set(ROLES['site']))
    assert 'rosy-site-tools-autoupdate.timer' in ROLES['site']
    assert 'rosy-omx-arm-status.service' in ROLES['omx']
    assert 'rosy-omx-devices-autoupdate.timer' in ROLES['omx']
