"""A valid signature alone cannot make a legacy SDK safe for A/B shared state."""
import ast
import copy
import json
import shutil
import subprocess
import sys

import pytest

from build_payload_release import seal_release
from signing import sign_checksums
from test_os_factory_release import _device, _factory, FACTORY_ID
from test_factory_release_signature import _keys, ROOT


CONTRACT = {"schema_version": 1, "boot_abi": {"min": 1, "max": 1},
            "state_schema": {"read_min": 1, "read_max": 1, "write": 1}}
CANDIDATE = "2026.10.26-010"


def _candidate(tmp_path, monkeypatch, contract, *, missing_closure=False):
    first, root, _, _, private, public, _ = _device(tmp_path, monkeypatch)
    descriptor = root / "etc/rosy/os-factory-release.json"
    original = descriptor.read_bytes()
    release, _ = _factory(root, CANDIDATE, private, public)
    descriptor.write_bytes(original)
    engine = release / "deploy/robot/native/image_layer_boot.py"
    lines = engine.read_text().splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    removals = [node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "OS_COMPATIBILITY" for t in node.targets)]
    for node in reversed(removals):
        del lines[node.lineno - 1:node.end_lineno]
    if missing_closure:
        tree = ast.parse("".join(lines))
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "ENGINE_FILES" for t in n.targets))
        files = tuple(name for name in ast.literal_eval(node.value) if name != "os_state_ready.py")
        lines[node.lineno - 1:node.end_lineno] = ["ENGINE_FILES = " + repr(files) + "\n"]
    if contract is not None:
        lines.append("\nOS_COMPATIBILITY = " + repr(contract) + "\n")
    engine.write_text("".join(lines))
    for name in ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig"):
        (release / name).unlink(missing_ok=True)
    seal_release(release, CANDIDATE)
    (release / "SHA256SUMS.sig").write_text(sign_checksums((release / "SHA256SUMS").read_bytes(), private) + "\n")
    current = root / "opt/rosy/current"
    current.symlink_to("releases/" + FACTORY_ID)
    calls = []
    manager = first._native_release().NativeReleaseManager(root=root, public_key=root / first.TRUSTED_RELEASE_KEY,
        runtime=calls.append, io_active=lambda: False)
    return manager, current, calls


def test_signed_compatible_sdk_can_activate_on_ab(tmp_path, monkeypatch):
    manager, current, calls = _candidate(tmp_path, monkeypatch, CONTRACT)
    assert manager.activate(CANDIDATE)["ok"]
    assert current.resolve().name == CANDIDATE
    assert calls == ["stop", "start"]


@pytest.mark.parametrize("maximum", [1, 2])
def test_protocol2_requires_a_signed_sdk_that_preserves_boot_abi2(tmp_path, monkeypatch, maximum):
    from os_payload_compatibility import require_ab_payload
    contract = copy.deepcopy(CONTRACT)
    contract["boot_abi"]["max"] = maximum
    _, current, _ = _candidate(tmp_path, monkeypatch, contract)
    root = current.parents[2]
    path = root / "etc/rosy/os-slot.json"
    layout = dict(json.loads(path.read_text()), schema_version=2)
    path.write_text(json.dumps(layout))
    (root / "proc/cmdline").write_text(f"root=PARTUUID={layout['root_partuuid']} rosy.os_layout=ab-v2\n")
    candidate = root / "opt/rosy/releases" / CANDIDATE
    if maximum == 1:
        with pytest.raises(ValueError, match="OS_PAYLOAD_INCOMPATIBLE.*boot ABI"):
            require_ab_payload(root, candidate)
    else:
        require_ab_payload(root, candidate)


@pytest.mark.parametrize("change", ["legacy", "boolean_schema", "boot_abi", "reader", "writer", "closure"])
def test_incompatible_signed_sdk_is_refused_before_activation_mutates_state(tmp_path, monkeypatch, change):
    contract = copy.deepcopy(CONTRACT)
    if change == "legacy":
        contract = None
    elif change == "boolean_schema":
        contract["schema_version"] = True
    elif change == "boot_abi":
        contract["boot_abi"] = {"min": 2, "max": 2}
    elif change == "reader":
        contract["state_schema"]["read_min"] = 2
        contract["state_schema"]["read_max"] = 2
    elif change == "writer":
        contract["state_schema"]["write"] = 2
    manager, current, calls = _candidate(tmp_path, monkeypatch, contract, missing_closure=change == "closure")
    before = current.resolve()
    with pytest.raises(ValueError, match="OS_PAYLOAD_INCOMPATIBLE"):
        manager.activate(CANDIDATE)
    assert current.resolve() == before
    assert calls == []
    assert not manager.journal.exists()


def test_legacy_standalone_verifier_still_needs_only_its_existing_signing_helper(tmp_path):
    private, public = _keys(tmp_path / "offline", "fixture")
    root = tmp_path / "legacy"
    _factory(root, FACTORY_ID, private, public, signed=True)
    runtime = tmp_path / "standalone"
    runtime.mkdir()
    shutil.copy2(ROOT / "deploy/robot/pinky_pro/native/native_release.py", runtime / "native_release.py")
    shutil.copy2(ROOT / "deploy/hosts/common/release/signing.py", runtime / "signing.py")
    result = subprocess.run([sys.executable, "-E", "-s", "-B", str(runtime / "native_release.py"),
        "--root", str(root), "--public-key", str(root / "etc/rosy/trusted-release-keys" / public.name),
        "verify", "--release-id", FACTORY_ID], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_explicit_rollback_cannot_reintroduce_a_legacy_sdk(tmp_path, monkeypatch):
    manager, current, calls = _candidate(tmp_path, monkeypatch, None)
    manager.links.set("previous", CANDIDATE)
    before = current.resolve()
    with pytest.raises(ValueError, match="OS_PAYLOAD_INCOMPATIBLE"):
        manager.rollback()
    assert current.resolve() == before
    assert calls == []
    assert not manager.journal.exists()
