"""The actual provisioning and join owners share a one-time channel across slots."""
import json
import pytest

from os_state_boot_fakes import shared_roots
from test_first_boot_provisioning import _bundle, _module
from test_os_first_boot_state import SERIAL
from test_os_tailnet_state import _serial
from test_rosy_tailscale_join import KEY, _load, _Recorder, _join_file


def _device(tmp_path, monkeypatch):
    roots = shared_roots(tmp_path, monkeypatch)
    root, other, common, _ = roots
    bundle = root / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle(tailscale_auth_key=KEY)))
    first = _module()
    assert first.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)["ok"]
    for target in (root, other):
        _serial(target)
    first._native_helper("os_state_storage").admit_tailnet(root, bind_machine=True)
    return first, root, other, common, bundle


def test_join_consumption_survives_b_then_return_to_a_and_ignores_old_local_input(tmp_path, monkeypatch):
    first, root, other, common, bundle = _device(tmp_path, monkeypatch)
    request = common / "tailscale/join/request.json"
    assert request.is_file(), "firstboot must publish one shared request, not an A-only key"
    assert KEY in request.read_text()
    module = _load("shared_tailnet_join")
    recorder = _Recorder()
    monkeypatch.setattr(module, "_invoke", recorder)
    monkeypatch.setenv("ROSY_TAILSCALE_CLI", "/usr/bin/tailscale")
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(other))
    assert first.FirstBootProvisioner(root=other).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert module.main() == 0
    assert KEY not in request.read_text()
    assert recorder.key_material == [KEY]
    assert json.loads((common / "tailscale/join/result.json").read_text())["status"] == "joined"
    _join_file(root)  # A's stale root-local card channel must never be replayed.
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(root))
    recorder.calls.clear()
    assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert module.main() == 0
    assert recorder.calls == []
    assert KEY not in request.read_text()


def test_join_refuses_a_different_board_before_any_cli_call_or_key_consumption(tmp_path, monkeypatch):
    _, root, _, common, _ = _device(tmp_path, monkeypatch)
    _serial(root, "10000000abcdef02")
    module = _load("moved_tailnet_join")
    calls = []
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(root))
    monkeypatch.setattr(module, "_invoke", lambda *args: calls.append(args))
    assert module.main() == 1
    assert calls == []
    assert KEY in (common / "tailscale/join/request.json").read_text()


def test_failed_join_preserves_shared_key_and_scrubs_errors(tmp_path, monkeypatch):
    _, root, _, common, _ = _device(tmp_path, monkeypatch)
    module = _load("failed_shared_join")
    recorder = _Recorder(up_rc=1, up_stderr="fixture error " + KEY)
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(root))
    monkeypatch.setenv("ROSY_TAILSCALE_CLI", "/usr/bin/tailscale")
    monkeypatch.setattr(module, "_invoke", recorder)
    assert module.main() == 1
    assert KEY in (common / "tailscale/join/request.json").read_text()
    result = (common / "tailscale/join/result.json").read_text()
    assert KEY not in result
    assert json.loads(result)["status"] == "failed"


def test_other_slot_cannot_spend_the_same_request_while_join_is_running(tmp_path, monkeypatch):
    _, root, other, _, _ = _device(tmp_path, monkeypatch)
    module = _load("serialized_shared_join")
    recorder = _Recorder()
    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(root))
    monkeypatch.setenv("ROSY_TAILSCALE_CLI", "/usr/bin/tailscale")

    def invoke(argv, timeout):
        if argv[1] == "status":
            with monkeypatch.context() as scoped:
                scoped.setenv("ROSY_TAILSCALE_ROOT", str(other))
                assert module.main() == 1
        return recorder(argv, timeout)

    monkeypatch.setattr(module, "_invoke", invoke)
    assert module.main() == 0
    assert [call[1] for call in recorder.calls] == ["status", "up"]


def test_join_does_not_scrub_a_replacement_request_after_up(tmp_path, monkeypatch):
    _, root, _, common, _ = _device(tmp_path, monkeypatch)
    request = common / "tailscale/join/request.json"
    module = _load("changed_shared_join")
    recorder = _Recorder()
    replacement = json.loads(request.read_text())
    replacement["auth_key"] = KEY + "new"

    def invoke(argv, timeout):
        done = recorder(argv, timeout)
        if argv[1] == "up":
            request.write_text(json.dumps(replacement))
        return done

    monkeypatch.setenv("ROSY_TAILSCALE_ROOT", str(root))
    monkeypatch.setenv("ROSY_TAILSCALE_CLI", "/usr/bin/tailscale")
    monkeypatch.setattr(module, "_invoke", invoke)
    assert module.main() == 1
    assert json.loads(request.read_text()) == replacement
