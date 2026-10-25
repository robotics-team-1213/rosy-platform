"""Signed boot-support continuity; fake roots and runners never touch a host service."""

from __future__ import annotations

import hashlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from auto_update_fakes import CURRENT, NEXT, NEWER, REPO, device, host, hub, keys, updater


NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
OLD, NEW = "2026.10.23-001", "2026.10.24-001"
BOOT = "opt/rosy/first-boot/rosy-first-boot.py"
UNIT = "etc/systemd/system/rosy-network-recovery.service"
CATALOG = "image-layer/boot/catalog.json"


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), NATIVE / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def payload(root, release=NEW):
    native = root / "opt/rosy/releases" / release / "deploy/robot/native"
    content = b"# signed first boot with network handoff\n"
    write(native / "image-layer/boot/rosy-first-boot.py", content.decode())
    write(native / CATALOG, json.dumps({"schema": 1, "files": {
        "rosy-first-boot.py": hashlib.sha256(content).hexdigest(),
    }}))
    write(native / "rosy-network-recovery.service", "[Service]\nExecStart=/bin/true\n")
    return native


def bridge(root):
    installed = root / "opt/rosy/native-runtime"
    old = root / "opt/rosy/releases" / OLD / "deploy/robot/native"
    for name in ("sync-image-layer.py", "image-layer-reconcile.py", "auto_update_apply.py",
                 "auto_update_records.py", "auto_update_host.py", "auto_update_stage.py", "os_state_layout.py",
                 "rosy_auto_update.py", "rosy_claim.py",
                 "image_layer_boot.py", "image_layer_files.py"):
        source = NATIVE / name
        text = source.read_text(encoding="utf-8") if source.exists() else "# missing bridge implementation\n"
        write(installed / name, text)
        write(old / name, text)
    (root / "opt/rosy/previous").symlink_to("releases/" + OLD)


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        code = 3 if argv[:2] == ["systemctl", "is-active"] else 0
        return subprocess.CompletedProcess(argv, code, "", "")


def sync(root, release=NEW, *, runner=None, verify=None):
    return module("sync-image-layer").sync(
        root, dry_run=False, verify=verify or (lambda _: None), runner=runner or Runner(),
        is_link=lambda _: True, readlink=lambda _: "releases/" + release,
    )


def test_feature_refuses_old_installed_engine_before_any_image_write(tmp_path):
    payload(tmp_path)
    write(tmp_path / BOOT, "old first boot")
    with pytest.raises(ValueError, match="BRIDGE_REQUIRED"):
        sync(tmp_path)
    assert (tmp_path / BOOT).read_text() == "old first boot"
    assert not (tmp_path / UNIT).exists()


def test_bridge_accepts_the_previous_engine_declared_closure_without_a_new_helper(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    for native in (tmp_path / "opt/rosy/native-runtime", tmp_path / "opt/rosy/releases" / OLD / "deploy/robot/native"):
        metadata = native / "image_layer_boot.py"
        metadata.write_text(metadata.read_text().replace(', "os_state_layout.py"', ''), encoding="utf-8")
        (native / "os_state_layout.py").unlink()
    verified = []
    assert module("image_layer_boot").require_bridge(tmp_path, NEW, verified.append) == OLD
    assert verified == [OLD]


def test_new_bridge_does_not_accept_a_missing_declared_helper(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    (tmp_path / "opt/rosy/native-runtime/os_state_layout.py").unlink()
    with pytest.raises(ValueError, match="BRIDGE_REQUIRED"):
        sync(tmp_path)
    assert not (tmp_path / UNIT).exists()


@pytest.mark.parametrize("remove", [False, True])
def test_candidate_cannot_expand_paths_or_drop_the_base_bridge_contract(tmp_path, remove):
    payload(tmp_path)
    bridge(tmp_path)
    for native in (tmp_path / "opt/rosy/native-runtime", tmp_path / "opt/rosy/releases" / OLD / "deploy/robot/native"):
        path = native / "image_layer_boot.py"
        text = path.read_text()
        text = text.replace('"auto_update_host.py", ', '') if remove else text.replace('ENGINE_FILES = (', 'ENGINE_FILES = ("../escape.py", ')
        path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="BRIDGE_REQUIRED"):
        sync(tmp_path)


def test_signed_catalog_reaches_boot_and_preserves_device_data(tmp_path):
    native = payload(tmp_path)
    bridge(tmp_path)
    private = ["etc/rosy/device.json", "var/lib/rosy/maps/site.yaml", "etc/rosy/calibration.json",
               "etc/NetworkManager/system-connections/operator.nmconnection"]
    for name in private:
        write(tmp_path / name, "per-device bytes")
    verified = []
    sync(tmp_path, verify=verified.append)
    assert (tmp_path / BOOT).read_bytes() == (native / "image-layer/boot/rosy-first-boot.py").read_bytes()
    assert (tmp_path / UNIT).is_file()
    assert OLD in verified and NEW in verified
    assert all((tmp_path / name).read_text() == "per-device bytes" for name in private)


@pytest.mark.parametrize("bad_name", ["../../etc/rosy/device.json", "runtime.env", "operator.nmconnection"])
def test_catalog_cannot_expand_the_compiled_allowlist(tmp_path, bad_name):
    native = payload(tmp_path)
    bridge(tmp_path)
    write(native / CATALOG, json.dumps({"schema": 1, "files": {bad_name: "a" * 64}}))
    with pytest.raises(ValueError, match="BOOT_CATALOG"):
        sync(tmp_path)
    assert not (tmp_path / UNIT).exists()


def test_catalog_hash_mismatch_is_rejected_before_mutation(tmp_path):
    native = payload(tmp_path)
    bridge(tmp_path)
    write(native / "image-layer/boot/rosy-first-boot.py", "tampered")
    with pytest.raises(ValueError, match="BOOT_CATALOG"):
        sync(tmp_path)


def test_modified_installed_bridge_does_not_advertise_capability(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / "opt/rosy/native-runtime/auto_update_apply.py", "# local override")
    with pytest.raises(ValueError, match="BRIDGE_REQUIRED"):
        sync(tmp_path)


def test_unverified_bridge_release_cannot_authorize_feature(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)

    def verify(release):
        if release == OLD:
            raise ValueError("SIGNATURE_INVALID: bridge")

    with pytest.raises(ValueError, match="BRIDGE_REQUIRED|SIGNATURE_INVALID"):
        sync(tmp_path, verify=verify)
    assert not (tmp_path / BOOT).exists()


def test_missing_bridge_dependency_refuses_feature(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    (tmp_path / "opt/rosy/native-runtime/image-layer-reconcile.py").unlink()
    with pytest.raises(ValueError, match="BRIDGE_REQUIRED"):
        sync(tmp_path)


def test_legacy_payload_remains_a_bridge_without_boot_mutation(tmp_path):
    native = payload(tmp_path)
    shutil.rmtree(native / "image-layer/boot")
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    assert (tmp_path / BOOT).read_text() == "image baseline"


def test_inverse_restores_boot_and_disables_new_unit_before_legacy_sync(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    runner = Runner()
    result = module("sync-image-layer").inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=runner)
    assert result["ok"] is True
    assert (tmp_path / BOOT).read_text() == "image baseline"
    assert not (tmp_path / UNIT).exists()
    assert ["systemctl", "disable", "--now", "rosy-network-recovery.service"] in runner.calls
    assert ["systemctl", "daemon-reload"] in runner.calls
    # Repeated inverse after power loss must be harmless.
    module("sync-image-layer").inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=runner)


def test_inverse_damage_holds_and_keeps_new_coordinator(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    write(tmp_path / BOOT, "unexplained local mutation")
    with pytest.raises(ValueError, match="BOOT_INVERSE"):
        module("sync-image-layer").inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=Runner())
    assert (tmp_path / "opt/rosy/native-runtime/image_layer_boot.py").exists()


def test_inverse_retries_interrupted_restore(tmp_path, monkeypatch):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    engine = module("sync-image-layer")
    original = engine._install

    def interrupted(source, destination, mode):
        original(source, destination, mode)
        raise OSError("power interrupted after rename")

    monkeypatch.setattr(engine, "_install", interrupted)
    with pytest.raises(OSError):
        engine.inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=Runner())
    monkeypatch.setattr(engine, "_install", original)
    engine.inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=Runner())
    assert (tmp_path / BOOT).read_text() == "image baseline"
    assert not (tmp_path / UNIT).exists()


def test_boot_recovery_runs_inverse_when_release_recovery_returned_to_old(tmp_path, monkeypatch):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    (tmp_path / "opt/rosy/current").symlink_to("releases/" + OLD)
    engine = module("sync-image-layer")
    monkeypatch.setattr(engine, "_verifier", lambda *_: lambda _: None)
    entry = module("image-layer-reconcile")
    monkeypatch.setattr(entry, "_sync_module", lambda: engine)
    entry.reconcile_at_boot(tmp_path, Runner())
    assert (tmp_path / BOOT).read_text() == "image baseline"
    assert not (tmp_path / UNIT).exists()


def test_legacy_backup_history_never_contains_new_boot_paths(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    for manifest in (tmp_path / "var/lib/rosy/image-layer-backup").glob("*/backup-manifest.json"):
        paths = {record["path"] for record in json.loads(manifest.read_text())["files"]}
        assert "/" + BOOT not in paths


def test_boot_reconcile_finishes_partial_forward_boot_files(tmp_path, monkeypatch):
    native = payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    (tmp_path / "opt/rosy/current").symlink_to("releases/" + NEW)
    engine = module("sync-image-layer")
    monkeypatch.setattr(engine, "_verifier", lambda *_: lambda _: None)
    entry = module("image-layer-reconcile")
    monkeypatch.setattr(entry, "_sync_module", lambda: engine)
    entry.reconcile_at_boot(tmp_path, Runner())
    assert (tmp_path / BOOT).read_bytes() == (native / "image-layer/boot/rosy-first-boot.py").read_bytes()


def test_boot_reconcile_undoes_boot_when_partial_native_install_is_undone(tmp_path, monkeypatch):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    manifest = next((tmp_path / "var/lib/rosy/image-layer-backup").glob("*/backup-manifest.json"))
    record = json.loads(manifest.read_text())
    record["files_applied"] = False
    write(manifest, json.dumps(record))
    missing = next(item for item in record["files"] if item["state"] == "new"
                   and item["path"].startswith("/opt/rosy/native-runtime/"))
    (tmp_path / missing["path"].lstrip("/")).unlink()
    write(tmp_path / BOOT, "image baseline")
    (tmp_path / "opt/rosy/current").symlink_to("releases/" + NEW)
    engine = module("sync-image-layer")
    monkeypatch.setattr(engine, "_verifier", lambda *_: lambda _: None)
    entry = module("image-layer-reconcile")
    monkeypatch.setattr(entry, "_sync_module", lambda: engine)
    entry.reconcile_at_boot(tmp_path, Runner())
    assert (tmp_path / BOOT).read_text() == "image baseline"
    assert not (tmp_path / UNIT).exists()


def test_prepare_is_durable_before_first_boot_replace(tmp_path, monkeypatch):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    engine = module("sync-image-layer")
    original = engine._install
    observed = []

    def observe(source, destination, mode):
        if destination == tmp_path / BOOT:
            journal = tmp_path / "var/lib/rosy/image-layer-backup/boot-transition.json"
            record = json.loads(journal.read_text())
            assert record["release_id"] == NEW and record["previous_release"] == OLD
            assert journal.stat().st_mode & 0o777 == 0o600
            observed.append(True)
        return original(source, destination, mode)

    monkeypatch.setattr(engine, "_install", observe)
    engine.sync(tmp_path, dry_run=False, verify=lambda _: None, runner=Runner(),
                is_link=lambda _: True, readlink=lambda _: "releases/" + NEW)
    assert observed


@pytest.mark.parametrize("relative,content", [
    ("var/lib/rosy/network/transaction.json", '{"state":"activating"}'),
    ("var/lib/rosy/network/transaction.json", '{"state":"held"}'),
    ("var/lib/rosy/network/transaction.json", 'not json'),
    ("run/rosy-network/recovery.json", '{"active":true,"boot_id":"boot"}'),
    ("run/rosy-network/recovery.json", '{"active":null}'),
])
def test_live_or_unknown_network_state_defers_update(device, host, hub, relative, content):
    write(device / relative, content)
    report = updater(host, hub).eligibility(waive_inputs=True)
    assert report["eligible"] is False
    assert any("network" in reason for reason in report["reasons"])


@pytest.mark.parametrize("terminal", ["committed", "rolled_back", "rejected"])
def test_terminal_network_result_does_not_block_updates(device, host, hub, terminal):
    write(device / "var/lib/rosy/network/transaction.json", json.dumps({"state": terminal}))
    assert updater(host, hub).eligibility(waive_inputs=True)["eligible"] is True


def test_rollback_tail_stops_before_legacy_sync_when_inverse_is_unverified(device, host, hub, monkeypatch):
    update = updater(host, hub)
    calls = []

    def inverse(_release):
        from auto_update_host import UpdateError
        calls.append("inverse")
        raise UpdateError("BOOT_INVERSE: backup is corrupt")

    monkeypatch.setattr(update, "_inverse_boot_layer", inverse, raising=False)
    monkeypatch.setattr(update, "_sync", lambda _: calls.append("legacy sync"))
    problems = update._rollback_tail("2026.10.24-001")
    assert calls == ["inverse"]
    assert any("BOOT_INVERSE" in problem for problem in problems)


def test_runtime_incompatibility_reports_image_required_without_switching(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda *_: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_PYTHON_RUNTIME: signed image required"}), "")
    result = updater(host, hub).run()
    assert result["phase"] == "image_required"
    assert result["current_release"] == CURRENT
    assert result["last_result"]["outcome"] == "image_required"


@pytest.mark.parametrize("lost", ["missing", "replaced", "expired"])
def test_lost_update_claim_defers_before_next_mutating_step(device, host, hub, lost):
    import rosy_claim
    from auto_update_host import CLAIM_HOLDER, Deferred

    if lost != "missing":
        holder = "network-maintenance" if lost == "replaced" else CLAIM_HOLDER
        rosy_claim.acquire(device, holder, "test contention", 1, now=host.now())
        if lost == "expired":
            host.t += dt.timedelta(seconds=2)
    update = updater(host, hub)
    with pytest.raises(Deferred, match="claim"):
        update._journal({"applying": {"release_id": NEXT}}, "image-layer-sync")


def test_bridge_selector_discovers_v2_with_the_same_signed_rollout(device, host, hub, keys):
    hub.publish(keys, NEXT)
    signed = hub.publish(keys, NEWER)
    hub.releases[-1]["tag_name"] = "payload-v2-" + NEWER
    legacy_tag = re.compile(r"^payload-([0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3})$")
    assert legacy_tag.fullmatch(hub.releases[0]["tag_name"])
    assert legacy_tag.fullmatch(hub.releases[1]["tag_name"]) is None
    update = updater(host, hub)
    releases = update._releases({}, REPO)
    assert {item["release_id"] for item in releases} == {NEXT, NEWER}
    feature = next(item for item in releases if item["release_id"] == NEWER)
    assert update._rollout(feature) == signed


def test_v2_selector_ignores_legacy_cache_and_never_leaks_features_into_it(device, host, hub, keys):
    hub.publish(keys, NEXT)
    hub.publish(keys, NEWER)
    hub.releases[-1]["tag_name"] = "payload-v2-" + NEWER
    old_cache = [{"release_id": NEXT}]
    cache = {"etag": hub.etag, "releases": old_cache.copy()}
    releases = updater(host, hub)._releases(cache, REPO)
    assert {item["release_id"] for item in releases} == {NEXT, NEWER}
    assert cache["releases"] == old_cache  # A downgraded legacy engine may still consume this cache.


def test_v2_discovery_does_not_bypass_rollout_signature(device, host, hub, keys):
    from auto_update_host import Definitive

    hub.publish(keys, NEWER, bad_signature=True)
    hub.releases[-1]["tag_name"] = "payload-v2-" + NEWER
    update = updater(host, hub)
    releases = update._releases({}, REPO)
    assert len(releases) == 1
    with pytest.raises(Definitive, match="ROLLOUT_SIGNATURE"):
        update._rollout(releases[0])


@pytest.mark.parametrize("inactive", ["rosy-network-agent.service", "rosy-network-recovery.timer"])
def test_feature_health_requires_the_agent_and_recovery_timer(device, host, hub, inactive):
    payload(device, CURRENT)
    for unit in ("rosy-network-agent.service", "rosy-network-recovery.timer"):
        write(device / "etc/systemd/system" / unit, "[Unit]\n")
    host.overrides["is-active"] = lambda _host, argv: (
        subprocess.CompletedProcess([], 3, "", "") if argv[-1] == inactive else None)
    problems = updater(host, hub)._unit_problems(CURRENT, {"active": {}, "failed": []})
    assert any(inactive in problem for problem in problems)


def test_operator_inverse_preflight_validates_previous_without_mutation(tmp_path, monkeypatch):
    native = payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    (tmp_path / "opt/rosy/current").symlink_to("releases/" + NEW)
    engine, runner = module("sync-image-layer"), Runner()
    monkeypatch.setattr(engine, "_verifier", lambda *_: lambda _: None)
    code = engine.main(["--root", str(tmp_path), "--inverse-before-legacy-sync",
                        "--rollback-target-previous", "--dry-run"], runner=runner)
    assert code == 0
    assert (tmp_path / BOOT).read_bytes() == (native / "image-layer/boot/rosy-first-boot.py").read_bytes()
    assert (tmp_path / UNIT).exists() and not runner.calls


def test_completed_inverse_clears_active_journal_for_legacy_engine(tmp_path):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    module("sync-image-layer").inverse_boot_layer(tmp_path, OLD, verify=lambda _: None, runner=Runner())
    assert not (tmp_path / "var/lib/rosy/image-layer-backup/boot-transition.json").exists()


def test_boot_reconcile_propagates_inverse_failure_and_retains_journal(tmp_path, monkeypatch):
    payload(tmp_path)
    bridge(tmp_path)
    write(tmp_path / BOOT, "image baseline")
    sync(tmp_path)
    (tmp_path / "opt/rosy/current").symlink_to("releases/" + OLD)
    write(tmp_path / BOOT, "unexplained local mutation")
    journal = tmp_path / "var/lib/rosy/image-layer-backup/boot-transition.json"
    before = journal.read_bytes()
    engine = module("sync-image-layer")
    monkeypatch.setattr(engine, "_verifier", lambda *_: lambda _: None)
    entry = module("image-layer-reconcile")
    monkeypatch.setattr(entry, "_sync_module", lambda: engine)
    runner = Runner()
    with pytest.raises(ValueError, match="BOOT_INVERSE"):
        entry.reconcile_at_boot(tmp_path, runner)
    assert journal.read_bytes() == before
    assert (tmp_path / BOOT).read_text() == "unexplained local mutation"
    assert runner.calls == []
