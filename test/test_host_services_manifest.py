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
