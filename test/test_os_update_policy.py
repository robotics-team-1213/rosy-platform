"""OS policy shares native operator controls; mounts and CORE production are modeled."""
import importlib
import json

import pytest

from auto_update_fakes import FakeHost
from test_os_update_state import _state, _begin, SOURCE_BOOT, TRANSACTION


def _policy(tmp_path, monkeypatch):
    state, root, journal, _, verified, facts = _state(tmp_path, monkeypatch)
    module = importlib.import_module("os_update_policy")
    records = importlib.import_module("auto_update_records")
    directory = root / "var/lib/rosy-device/policy/updates"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text('{"enabled":true}')
    monkeypatch.setattr(records, "policy_file", lambda r, name: directory / name)
    boot = root / "proc/sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text(SOURCE_BOOT)
    host = FakeHost(root)
    host.write_inputs()
    import rosy_claim
    rosy_claim.acquire(root, "os-update:" + TRANSACTION, "OS fixture", 300, now=host.now())
    return module, state, root, journal, verified, facts, directory, host


@pytest.mark.parametrize("pending", [False, True])
def test_two_distinct_idle_samples_admit_own_transaction_without_policy_or_journal_writes(tmp_path, monkeypatch, pending):
    m, state, root, journal, verified, facts, directory, host = _policy(tmp_path, monkeypatch)
    if pending:
        _begin(state, root, verified, facts)
    before = {p: p.read_bytes() for p in (journal, directory / "config.json")}
    first = host.now()
    assert m.authorize(root, TRANSACTION, host=host) is None
    assert (host.now() - first).total_seconds() == 12
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (directory / "hold.json").exists()


@pytest.mark.parametrize("percent,charging,allowed", [
    (59, True, False), (59, False, False), (60, True, True), (60, False, True),
    (100, False, True), (101, False, False), (-1, True, False),
    (None, True, False), (float("nan"), True, False), (True, False, False),
    (80, "true", False), (80, None, False), (80, 1, False),
])
def test_os_battery_has_no_charging_exception_and_requires_known_values(tmp_path, monkeypatch, percent, charging, allowed):
    m, _, root, _, _, _, _, host = _policy(tmp_path, monkeypatch)
    host.inputs_changes = dict(battery_percent=percent, battery_charging=charging)
    host.write_inputs()
    if allowed:
        m.authorize(root, TRANSACTION, host=host)
    else:
        with pytest.raises(ValueError, match="OS_UPDATE_POLICY"):
            m.authorize(root, TRANSACTION, host=host)


@pytest.mark.parametrize("change", ["disabled", "hold", "network", "claim", "pending", "journal", "seal"])
def test_policy_and_ownership_are_rechecked_after_second_sample(tmp_path, monkeypatch, change):
    m, _, root, journal, _, _, directory, host = _policy(tmp_path, monkeypatch)
    original_sleep = host.sleep
    def sleep(seconds):
        original_sleep(seconds)
        if change == "disabled":
            (directory / "config.json").write_text('{"enabled":false}')
        elif change == "hold":
            (directory / "hold.json").write_text('{')
        elif change == "network":
            path = root / "var/lib/rosy/network/transaction.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"state":"applying"}')
        elif change == "claim":
            import rosy_claim
            rosy_claim.release(root, "os-update:" + TRANSACTION)
        elif change == "pending":
            value = json.loads(journal.read_text())
            value["unexpected"] = True
            journal.write_text(json.dumps(value))
        elif change == "journal":
            journal.unlink()
        else:
            from auto_update_host import APPROVALS
            marker = root / APPROVALS[0]
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(dict(release_id=host.current_release())))
    host.sleep = sleep
    with pytest.raises(ValueError):
        m.authorize(root, TRANSACTION, host=host)


@pytest.mark.parametrize("change", ["moving", "unchanged", "missing", "expired_claim"])
def test_missing_or_nonidle_core_and_expired_claim_never_waive_checks(tmp_path, monkeypatch, change):
    m, _, root, _, _, _, _, host = _policy(tmp_path, monkeypatch)
    if change == "moving":
        host.second_sample_changes = dict(velocity_linear=0.2)
    elif change == "unchanged":
        host.sleep = lambda seconds: None
    elif change == "missing":
        host.inputs_changes = None
        host.write_inputs()
    else:
        original_sleep = host.sleep
        host.sleep = lambda seconds: original_sleep(301)
    with pytest.raises(ValueError, match="OS_UPDATE_POLICY"):
        m.authorize(root, TRANSACTION, host=host)


def test_installed_frozen_engine_contains_all_policy_imports(tmp_path, monkeypatch):
    import subprocess
    import sys
    from test_os_factory_release import _device
    from test_os_frozen_firstboot import _prefix, _stage
    from test_image_layer_sync import sync_mod
    _, root, _, _, _, _, _ = _device(tmp_path, monkeypatch)
    _stage(_prefix(root))
    frozen = root / "opt/rosy/os-bootstrap/native-runtime"
    script = "import sys;sys.path.insert(0,sys.argv[1]);import os_update_policy;print(os_update_policy.__file__)"
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(frozen)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert str(frozen) in result.stdout
    for name in ("os_update_policy.py", "auto_update_records.py", "auto_update_host.py", "rosy_transfer.py"):
        with pytest.raises(ValueError, match="IMAGE_LAYER_DESTINATION"):
            sync_mod.check_destination("opt/rosy/os-bootstrap/native-runtime/" + name)


@pytest.mark.parametrize("configuration", ["{", '{"enabled":"true"}', '{"repo":false}'])
def test_invalid_common_policy_is_a_deferral_without_mutation(tmp_path, monkeypatch, configuration):
    m, _, root, journal, _, _, directory, host = _policy(tmp_path, monkeypatch)
    config = directory / "config.json"
    config.write_text(configuration)
    before = journal.read_bytes()
    with pytest.raises(ValueError, match="OS_UPDATE_POLICY"):
        m.authorize(root, TRANSACTION, host=host)
    assert config.read_text() == configuration and journal.read_bytes() == before


@pytest.mark.parametrize("change", ["transaction_id", "source_boot_id"])
def test_another_transaction_or_source_boot_is_never_authorized(tmp_path, monkeypatch, change):
    m, state, root, journal, verified, facts, _, host = _policy(tmp_path, monkeypatch)
    _begin(state, root, verified, facts)
    value = json.loads(journal.read_text())
    value["pending"][change] = "44444444-4444-4444-8444-444444444444"
    journal.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="OS_UPDATE_POLICY"):
        m.authorize(root, TRANSACTION, host=host)
