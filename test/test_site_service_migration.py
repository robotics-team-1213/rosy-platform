"""Current, staged and cold rollback use distinct authenticated candidate sets."""

import copy
import json
import os
import shutil

import pytest

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import host, OLD, NEW, _image_id, _tag
from site_migration_fakes import (
    CURRENT, LEGACY, HASH_LABEL, PROJECT_LABEL, SERVICE_LABEL, InventoryHost,
    RecordingHttp, release_world, updater_for, write_candidate,
)


def managed(machine, service):
    return {cid: row for cid, row in machine.containers.items()
            if row["Config"]["Labels"].get(SERVICE_LABEL) == service
            and row["Config"]["Labels"].get(PROJECT_LABEL) == upd.PROJECT
            and row["Config"]["Labels"].get(HASH_LABEL)}


def prepare_normal_recovery(host, *, present=True, stopped=False, partial=False, started=True):
    machine = InventoryHost(host.paths)
    target = host.paths.candidates / NEW
    write_candidate(target, NEW, CURRENT)
    machine.load_images(target)
    shutil.copy2(host.paths.site_env, host.paths.env_backup)
    upd.write_env_tag(host.paths.site_env, NEW)
    upd.swap_link(host.paths.link, target)
    machine.partial_new = ("fleet", "postgres") if partial else None
    if started:
        machine.restart()
    postgres = next(iter(managed(machine, "postgres")), "not-created")
    if not present and postgres in machine.containers:
        del machine.containers[postgres]
    elif stopped and postgres in machine.containers:
        machine.containers[postgres]["State"]["Running"] = False
    updater_for(host, machine).save_state({"failed": {}, "switch": {
        "previous": str(host.paths.candidates / OLD), "current": OLD,
        "commit": NEW, "tag": _tag(NEW)}})
    machine.events.clear()
    return machine, target, postgres


def assert_manual_and_volume(machine, manual, volume):
    assert machine.containers[machine.manual] == manual
    assert machine.volumes["postgres-data"] is volume
    assert all("--force" not in c and "-f" not in c and "--volumes" not in c
               and "-v" not in c for c in machine.calls
               if c[:3] in (["docker", "container", "stop"], ["docker", "container", "rm"]))
    assert not any(c[:2] == ["docker", "volume"] or "--remove-orphans" in c for c in machine.calls)


def test_fixture_inventory_does_not_follow_tag_or_link_and_restart_keeps_orphans(host):
    machine, target, postgres = prepare_normal_recovery(host)
    before = copy.deepcopy(machine.containers)
    upd.write_env_tag(host.paths.site_env, OLD)
    upd.swap_link(host.paths.link, host.paths.candidates / OLD)
    assert machine.containers == before
    machine.restart()
    assert machine.containers[postgres] == before[postgres]
    assert target.exists()


def test_fixture_compose_selector_keeps_canonical_fleet_and_global_inventory_keeps_manual(host):
    machine = InventoryHost(host.paths)
    global_ids = machine(["docker", "ps", "--all", "--quiet", "--filter",
                          f"label={PROJECT_LABEL}={upd.PROJECT}", "--filter",
                          f"label={SERVICE_LABEL}=fleet"]).stdout.splitlines()
    assert set(global_ids) == set(managed(machine, "fleet")) | {machine.manual}
    output = updater_for(host, machine)._compose(
        upd.read_env(host.paths.site_env), "ps", "--all", "--format", "json").stdout
    rows = [json.loads(line) for line in output.splitlines()]
    assert {r["ID"] for r in rows if r["Service"] == "fleet"} == set(managed(machine, "fleet"))
    assert machine.manual in machine.containers


@pytest.mark.parametrize("services", [LEGACY, CURRENT], ids=["legacy3", "current4"])
def test_current_candidate_uses_its_verified_service_set(host, services):
    machine = InventoryHost(host.paths, services, manual=False)
    updater = updater_for(host, machine)
    assert updater.run() == upd.EXIT_OK
    assert updater.load_state()["installed"]["commit"] == OLD
    assert machine.loaded == []


def test_legacy_to_current_inspects_staged_files_before_image_load(host):
    machine = InventoryHost(host.paths)
    http = RecordingHttp(*release_world(NEW, CURRENT))
    updater = updater_for(host, machine, http)
    assert updater.run() == upd.EXIT_OK
    target = host.paths.candidates / NEW
    load = machine.events.index(("load", target))
    assert any(e[0] == "config" and e[1] == target and e[2] == NEW
               for e in machine.events[:load])
    assert set(managed(machine, "postgres"))
    assert updater.load_state()["installed"]["commit"] == NEW


def test_target_compose_cannot_add_a_service_absent_from_its_signed_set(host):
    machine = InventoryHost(host.paths)
    http = RecordingHttp(*release_world(NEW, LEGACY, compose_services=CURRENT))
    updater = updater_for(host, machine, http)
    assert updater.run() == upd.EXIT_FAILED
    assert machine.loaded == []
    assert host.paths.link.resolve() == host.paths.candidates / OLD
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == OLD


def test_target_image_pin_is_checked_before_load_or_switch(host):
    machine = InventoryHost(host.paths)
    http = RecordingHttp(*release_world(NEW, CURRENT, image_override="unrelated:latest"))
    updater = updater_for(host, machine, http)
    assert updater.run() == upd.EXIT_FAILED
    assert machine.loaded == []
    assert host.paths.link.resolve() == host.paths.candidates / OLD


@pytest.mark.parametrize("partial", [False, True], ids=["full-start", "partial-start"])
def test_failed_four_service_health_removes_only_retired_postgres_before_legacy_restore(host, partial):
    machine = InventoryHost(host.paths, unhealthy={NEW})
    machine.partial_new = ("fleet", "postgres") if partial else None
    manual, volume = copy.deepcopy(machine.containers[machine.manual]), machine.volumes["postgres-data"]
    http = RecordingHttp(*release_world(NEW, CURRENT))
    updater = updater_for(host, machine, http)
    assert updater.run() == upd.EXIT_FAILED
    assert not managed(machine, "postgres")
    assert host.paths.link.resolve() == host.paths.candidates / OLD
    assert "switch" not in updater.load_state()
    actions = [e for e in machine.events if e[0] in ("stop", "remove")]
    assert [e[0] for e in actions] == ["stop", "remove"]
    assert actions[0][1] == actions[1][1]
    assert all(e[2:] == (NEW, host.paths.candidates / NEW) for e in actions)
    assert_manual_and_volume(machine, manual, volume)


@pytest.mark.parametrize("posture", ["full", "partial", "stopped", "absent",
                                   "linked-before-stop", "common-partial-stop"])
def test_cold_normal_rollback_reauthenticates_both_candidates_and_converges(host, posture):
    machine, target, postgres = prepare_normal_recovery(
        host, present=posture != "absent", stopped=posture == "stopped", partial=posture == "partial",
        started=posture not in ("linked-before-stop", "common-partial-stop"))
    if posture == "common-partial-stop":
        del machine.containers[next(iter(managed(machine, "fleet")))]
    manual, volume = copy.deepcopy(machine.containers[machine.manual]), machine.volumes["postgres-data"]
    machine.add_container("manual-postgres", "postgres", NEW, managed=False)
    manual_pg = copy.deepcopy(machine.containers["manual-postgres"])
    http = RecordingHttp()
    cold = updater_for(host, machine, http)
    assert cold._accepted_images == {}
    assert cold.run() == upd.EXIT_FAILED  # recovered, not a new installation
    assert not managed(machine, "postgres")
    assert "switch" not in cold.load_state()
    assert cold.load_state()["last_run"]["result"] == "recovered"
    assert http.gets == []
    assert (target.resolve(), True) in machine.verifications
    assert ((host.paths.candidates / OLD).resolve(), True) in machine.verifications
    actions = [e for e in machine.events if e[0] in ("stop", "remove")]
    assert [e[0] for e in actions] == ([] if posture in ("absent", "linked-before-stop", "common-partial-stop") else
                                    ["remove"] if posture == "stopped" else ["stop", "remove"])
    assert all(e[1] == postgres and e[2:] == (NEW, target) for e in actions)
    assert machine.containers["manual-postgres"] == manual_pg
    assert_manual_and_volume(machine, manual, volume)


@pytest.mark.parametrize("fault", ["enumerate", "inspect", "stop", "remove", "remove-noop"])
def test_retirement_io_failure_is_not_absence_or_healthy_recovery(host, fault):
    machine, target, _ = prepare_normal_recovery(host)
    machine.fault = fault
    manual, volume = copy.deepcopy(machine.containers[machine.manual]), machine.volumes["postgres-data"]
    backup = host.paths.env_backup.read_bytes()
    cold = updater_for(host, machine)
    assert cold.run() == upd.EXIT_FAILED
    assert "switch" in cold.load_state()
    assert cold.load_state()["last_run"]["result"] == "recovery-pending"
    assert host.paths.link.resolve() == target
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == NEW
    assert host.paths.env_backup.read_bytes() == backup
    assert_manual_and_volume(machine, manual, volume)


@pytest.mark.parametrize("damage", ["image", "reference", "hash", "project", "service", "id", "duplicate"])
def test_retired_container_identity_conflict_never_stops_or_removes_it(host, damage):
    machine, target, postgres = prepare_normal_recovery(host)
    if damage == "duplicate":
        machine.add_container("duplicate-postgres", "postgres", NEW)
    else:
        def patch(row):
            if row["Id"] != postgres:
                return
            if damage == "image":
                row["Image"] = "sha256:" + "9" * 64
            elif damage == "reference":
                row["Config"]["Image"] = f"rosy-site-postgres:{OLD}"
            elif damage == "hash":
                row["Config"]["Labels"][HASH_LABEL] = "wrong-config-hash"
            elif damage == "project":
                row["Config"]["Labels"][PROJECT_LABEL] = "another-project"
            elif damage == "service":
                row["Config"]["Labels"][SERVICE_LABEL] = "fleet"
            else:
                row["Id"] = "replacement-container"
        machine.inspect_patch = patch  # lookup was valid; inspection is now inconsistent
    cold = updater_for(host, machine)
    assert cold.run() == upd.EXIT_FAILED
    assert "switch" in cold.load_state()
    assert host.paths.link.resolve() == target
    assert not any(e[0] in ("stop", "remove") for e in machine.events)
    assert postgres in machine.containers


@pytest.mark.parametrize("evidence", ["outgoing-signature", "outgoing-folder", "prior-signature", "backup", "outgoing-image"])
def test_cold_recovery_missing_evidence_refuses_without_cache_fallback(host, evidence):
    machine, target, _ = prepare_normal_recovery(host)
    if evidence == "outgoing-signature":
        (target / "release.json.sig").write_text("tampered")
    elif evidence == "outgoing-folder":
        target.rename(target.with_name("unavailable-target"))
    elif evidence == "prior-signature":
        (host.paths.candidates / OLD / "release.json.sig").write_text("tampered")
    elif evidence == "backup":
        upd.write_env_tag(host.paths.env_backup, NEW)
    else:
        del machine.image_ids[f"rosy-site-vision:{NEW}"]
    cold = updater_for(host, machine)
    cold._accepted_images[NEW] = {s: [_image_id(NEW, s)] for s in CURRENT}
    assert cold.run() == upd.EXIT_FAILED
    assert "switch" in cold.load_state()
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == NEW
    assert not any(e[0] in ("stop", "remove") for e in machine.events)


@pytest.mark.parametrize("services", [LEGACY, CURRENT], ids=["physical3", "physical4"])
@pytest.mark.parametrize("phase", ["before-rename", "after-rename", "after-link"])
def test_cold_physical_relocation_uses_original_current_path_and_retires_nothing(host, services, phase):
    machine = InventoryHost(host.paths, services)
    source = host.paths.candidates / OLD
    host.paths.link.unlink()
    source.rename(host.paths.link)
    # A colliding destination makes the original writer choose prev-<timestamp>.
    write_candidate(source, OLD, services)
    (source / "release.json.sig").write_text("unrelated invalid copy")
    previous = host.paths.candidates / "prev-20261026T000000Z"
    shutil.copy2(host.paths.site_env, host.paths.env_backup)
    if phase != "before-rename":
        os.rename(host.paths.link, previous)
        if phase == "after-link":
            upd.swap_link(host.paths.link, previous)
    write_candidate(host.paths.candidates / NEW, NEW, CURRENT)
    machine.load_images(host.paths.candidates / NEW)  # loaded is not started
    seed = updater_for(host, machine)
    seed.save_state({"failed": {}, "switch": {"previous": str(previous), "current": OLD,
                     "commit": OLD, "tag": _tag(OLD), "migration": True}})
    manual, volume = copy.deepcopy(machine.containers[machine.manual]), machine.volumes["postgres-data"]
    machine.events.clear()
    http = RecordingHttp()
    cold = updater_for(host, machine, http)
    assert cold.run() == upd.EXIT_FAILED
    assert "switch" not in cold.load_state()
    assert cold.load_state()["last_run"]["result"] == "recovered"
    assert host.paths.link.resolve() == previous
    assert all(folder != source and folder != host.paths.candidates / NEW
               for folder, _ in machine.verifications)
    assert all(loaded for _, loaded in machine.verifications)
    assert not any(e[0] in ("stop", "remove") for e in machine.events)
    assert bool(managed(machine, "postgres")) == (services == CURRENT)
    assert http.gets == []
    assert_manual_and_volume(machine, manual, volume)


def test_migration_flag_alone_cannot_bypass_normal_outgoing_authentication(host):
    machine, target, _ = prepare_normal_recovery(host)
    cold = updater_for(host, machine)
    state = cold.load_state()
    state["switch"]["migration"] = True  # inconsistent: commit NEW != current OLD
    cold.save_state(state)
    assert cold.run() == upd.EXIT_FAILED
    assert host.paths.link.resolve() == target
    assert "switch" in cold.load_state()
    assert not any(e[0] in ("stop", "remove") for e in machine.events)


@pytest.mark.parametrize("value", [None, "missing", "legacy", [], list(LEGACY[:2]),
                                   ["fleet", "fleet", "proxy"], [*CURRENT, "other"]])
def test_missing_or_unknown_verified_set_is_rejected_not_inferred(host, value):
    machine = InventoryHost(host.paths)
    machine.proof_patch = (lambda result: result.pop("verified_images")) if value == "missing" else (
        lambda result: result.update(verified_images=value))
    cold = updater_for(host, machine)
    with pytest.raises(upd.Rejected, match="service|verified|verification"):
        cold._verify(host.paths.candidates / OLD, loaded=True, expected_commit=OLD)


def test_partial_image_cache_is_not_a_verified_legacy_service_set(host):
    machine = InventoryHost(host.paths)
    cold = updater_for(host, machine)
    cold._accepted_images[OLD] = {s: [_image_id(OLD, s)] for s in LEGACY}
    assert cold.healthy(upd.read_env(host.paths.site_env), OLD)[0] is False


def test_dry_run_does_not_stage_or_claim_a_verified_target(host):
    machine = InventoryHost(host.paths)
    http = RecordingHttp(*release_world(NEW, CURRENT))
    updater = updater_for(host, machine, http, dry_run=True)
    assert updater.run() == upd.EXIT_OK
    assert http.downloads == [] and machine.loaded == []
    assert all(folder == (host.paths.candidates / OLD).resolve() for folder, _ in machine.verifications)
    assert not (host.paths.candidates / NEW).exists()


def test_retired_absence_does_not_clear_journal_until_legacy_health_passes(host):
    machine, _, _ = prepare_normal_recovery(host)
    machine.unhealthy.add(OLD)
    first = updater_for(host, machine)
    assert first.run() == upd.EXIT_FAILED
    assert not managed(machine, "postgres")
    assert "switch" in first.load_state()
    assert first.load_state()["last_run"]["result"] == "recovery-pending"
    machine.unhealthy.clear()
    cold = updater_for(host, machine)
    assert cold._accepted_images == {}
    assert cold.run() == upd.EXIT_FAILED
    assert "switch" not in cold.load_state()
    assert cold.load_state()["last_run"]["result"] == "recovered"


@pytest.mark.parametrize("physical", [False, True])
def test_journal_dry_run_never_performs_recovery_or_infers_a_target(host, physical):
    if physical:
        machine = InventoryHost(host.paths)
        shutil.copy2(host.paths.site_env, host.paths.env_backup)
        updater_for(host, machine).save_state({"failed": {}, "switch": {
            "previous": str(host.paths.candidates / OLD), "current": OLD, "commit": OLD,
            "tag": _tag(OLD), "migration": True}})
    else:
        machine, _, _ = prepare_normal_recovery(host)
    machine.events.clear()
    before = copy.deepcopy(machine.containers)
    updater = updater_for(host, machine, dry_run=True)
    assert updater.run() == upd.EXIT_FAILED
    assert updater.load_state()["last_run"]["result"] == "recovery-required"
    assert "switch" in updater.load_state()
    assert machine.containers == before and machine.events == []
    assert machine.verifications == []
