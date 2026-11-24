"""deploy/hosts/services.yaml: what tools/remote/update_status.py audits on each lab host."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = yaml.safe_load((ROOT / "deploy/hosts/services.yaml").read_text(encoding="utf-8"))["roles"]


def test_every_test_host_role_declares_the_storage_maintenance():
    # 2026-10-26: the site role lacked it, so the site PC had no cleanup and update_status never noticed.
    for role in ("model", "ai", "site", "omx"):
        units = ROLES[role]
        assert {"rosy-test-storage.service", "rosy-test-storage.timer"} <= set(units), role
        assert units["rosy-test-storage.timer"]["run"] == "timer", role


def test_native_omx_units_are_declared_once_separately_from_fleet_site_units():
    # AI PC hosts the D-1073 remote ACT HTTP service (`rosy-omx-act-http.service`); no OMX unit belongs on `site` or in two roles.
    by_role = {role: {n for n in units if n.startswith('rosy-omx-')} for role, units in ROLES.items()}
    assert by_role['omx'] and by_role['ai'] <= {'rosy-omx-act-http.service'}
    assert not by_role['site'] and not by_role['model']
    assert not (by_role['omx'] & by_role['ai'])
    assert 'rosy-site-tools-autoupdate.timer' in ROLES['site']
    assert 'rosy-omx-arm-status.service' in ROLES['omx']
    assert 'rosy-omx-devices-autoupdate.timer' in ROLES['omx']
