"""Real persisted pending state fences native maintenance after claim expiry; hardware is modeled."""
import ast
import copy
from datetime import datetime, timezone
import importlib
import json

import pytest

from test_os_payload_compatibility import _candidate, CONTRACT, CANDIDATE
from test_os_update_state import _state, _begin


def _pending_candidate(tmp_path, monkeypatch):
    m, journal_root, _, _, verified, facts = _state(tmp_path / "journal", monkeypatch)
    _begin(m, journal_root, verified, facts)
    pending = m.read_state(journal_root)
    contract = copy.deepcopy(CONTRACT)
    contract["boot_abi"]["max"] = 2
    manager, current, calls = _candidate(tmp_path / "device", monkeypatch, contract)
    root = manager.root
    descriptor = root / "etc/rosy/os-slot.json"
    layout = dict(json.loads(descriptor.read_text()), schema_version=2)
    descriptor.write_text(json.dumps(layout))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={layout['root_partuuid']} rosy.os_layout=ab-v2\n")
    directory = root / "var/lib/rosy-device/os-update"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "state.json"
    path.write_text(json.dumps(pending))
    path.chmod(0o600)
    monkeypatch.setattr(m, "mount_facts", lambda *args: [])
    return m, manager, current, calls, path


@pytest.mark.parametrize("operation", ["activate", "rollback"])
@pytest.mark.parametrize("claim", ["missing", "expired"])
def test_pending_blocks_native_activation_and_rollback_before_journal_or_runtime(tmp_path, monkeypatch, operation, claim):
    _, manager, current, calls, path = _pending_candidate(tmp_path, monkeypatch)
    if claim == "expired":
        import rosy_claim
        rosy_claim.acquire(manager.root, "os-update-fixture", "fixture", 1,
                           now=datetime(2000, 1, 1, tzinfo=timezone.utc))
        assert rosy_claim.check(manager.root) is None
    manager.links.set("previous", CANDIDATE)
    before, state = current.resolve(), path.read_bytes()
    with pytest.raises(ValueError, match="OS_UPDATE_PENDING"):
        manager.activate(CANDIDATE) if operation == "activate" else manager.rollback()
    assert current.resolve() == before and path.read_bytes() == state
    assert calls == [] and not manager.journal.exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_os_state_never_allows_native_maintenance_on_protocol2(tmp_path, monkeypatch, damage):
    _, manager, current, calls, path = _pending_candidate(tmp_path, monkeypatch)
    path.unlink() if damage == "missing" else path.write_text("{")
    before = current.resolve()
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        manager.activate(CANDIDATE)
    assert current.resolve() == before and calls == [] and not manager.journal.exists()


def test_idle_protocol2_allows_existing_signed_native_activation(tmp_path, monkeypatch):
    _, manager, current, calls, path = _pending_candidate(tmp_path, monkeypatch)
    value = json.loads(path.read_text())
    value["pending"] = None
    path.write_text(json.dumps(value))
    assert manager.activate(CANDIDATE)["ok"]
    assert current.resolve().name == CANDIDATE and calls == ["stop", "start"]


def test_abi2_sdk_without_pending_fence_is_rejected_even_if_it_claims_abi2(tmp_path, monkeypatch):
    _, manager, _, _, _ = _pending_candidate(tmp_path, monkeypatch)
    native = manager.root / "opt/rosy/releases" / CANDIDATE / "deploy/robot/native"
    path = native / "image_layer_boot.py"
    source = path.read_text()
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ENGINE_FILES" for t in n.targets))
    files = tuple(name for name in ast.literal_eval(node.value) if name != "os_update_state.py")
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = ["ENGINE_FILES = " + repr(files) + "\n"]
    path.write_text("".join(lines))
    # Metadata checker only: the activation path independently verifies the full signature first.
    m = importlib.import_module("os_payload_compatibility")
    with pytest.raises(ValueError, match="fence"):
        m.verify_contract(native, state_schema=1, boot_abi=2)
