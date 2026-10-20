"""Private lifecycle restrictions; no writer, native authority or device profile."""

from dataclasses import FrozenInstanceError, replace
import math
from uuid import uuid4

import pytest

from test_execution_budget import setup_budget


def fixture(*, max_parents=8, max_children=8):
    from core_features.command._execution_ledger import ChildIdentity, ExecutionIdentity, Ledger
    clock = [10.0]
    boot = uuid4()
    identity = ExecutionIdentity(
        robot_id="synthetic-robot", boot_id=boot, parent_id=uuid4(),
        profile_revision="SYNTHETIC", map_id="synthetic-map", map_revision="5",
        odom_frame="odom", odom_epoch="boot/odom-1", context_digest="0" * 64,
    )
    ledger = Ledger(robot_id=identity.robot_id, boot_id=boot, profile_revision="SYNTHETIC",
                    max_parents=max_parents, max_children=max_children, clock=lambda: clock[0])
    child = ChildIdentity(domain="navigation", boot_id=boot, run_id=uuid4(), generation=1)
    return ledger, identity, child, clock


def adopt(ledger, identity):
    budget, _ = setup_budget()
    parent = ledger.admit(identity, budget)
    assert parent is not None
    return parent


def test_installed_without_parent_is_required_wait():
    ledger, _, _, _ = fixture()
    status = ledger.read()
    assert status.state == "REQUIRED_WAIT"
    assert status.parent is None and status.child is None and status.remaining is None


def test_parent_and_child_changes_keep_original_budget():
    ledger, identity, child, clock = fixture()
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    first = ledger.read()
    assert ledger.revoke(parent, child)
    clock[0] = 10.2  # Past original initial admission cutoff, within its running window.
    following = replace(child, domain="docking", run_id=uuid4())
    assert ledger.attach(parent, following)
    later = ledger.read()
    assert later.parent == identity and later.child == following
    assert later.remaining.duration_s < first.remaining.duration_s - .199
    assert later.remaining.path_m < first.remaining.path_m - .199
    assert later.epoch > first.epoch


def test_identity_and_readback_are_frozen_observations():
    ledger, identity, _, _ = fixture()
    adopt(ledger, identity)
    with pytest.raises(FrozenInstanceError):
        identity.parent_id = uuid4()
    with pytest.raises(FrozenInstanceError):
        ledger.read().state = "ACTIVE"


@pytest.mark.parametrize("field,value", [("robot_id", "other"), ("boot_id", uuid4()),
                                        ("profile_revision", "other"), ("odom_frame", "map"),
                                        ("odom_epoch", "other")])
def test_scope_mismatch_cannot_adopt(field, value):
    ledger, identity, _, _ = fixture()
    budget, _ = setup_budget()
    assert ledger.admit(replace(identity, **{field: value}), budget) is None
    assert ledger.read().state == "REQUIRED_WAIT"


@pytest.mark.parametrize("elapsed", [.1, .11])
def test_held_budget_cannot_extend_initial_admission_cutoff(elapsed):
    ledger, identity, _, clock = fixture()
    budget, _ = setup_budget()
    clock[0] += elapsed
    assert ledger.admit(identity, budget) is None
    clock[0] = 10.0 + elapsed
    fresh, _ = setup_budget(before_mono=clock[0], after_mono=clock[0])
    assert ledger.admit(identity, fresh) is None  # Attempt consumed this boot's ID.


def test_parent_id_replay_and_capacity_never_evict_old_ids():
    ledger, identity, _, _ = fixture(max_parents=2)
    for ident in (identity, replace(identity, parent_id=uuid4())):
        parent = adopt(ledger, ident)
        assert not ledger.retire(parent)  # Explicit STOP before retirement.
        assert ledger.stop(parent, "test-stop")
        assert ledger.retire(parent)
    for ident in (identity, replace(identity, parent_id=uuid4())):
        budget, _ = setup_budget()
        assert ledger.admit(ident, budget) is None
    assert ledger.read().state == "REQUIRED_WAIT"


def test_exact_parent_late_cleanup_does_not_change_replacement():
    ledger, identity, child, _ = fixture()
    old = adopt(ledger, identity)
    assert ledger.attach(old, child)
    assert ledger.stop(old, "old-stop") and ledger.retire(old)
    current = adopt(ledger, replace(identity, parent_id=uuid4()))
    current_child = replace(child, run_id=uuid4(), generation=2)
    assert ledger.attach(current, current_child)
    for cleanup in (lambda: ledger.stop(old, "late"), lambda: ledger.retire(old),
                    lambda: ledger.revoke(old, child), lambda: ledger.revoke(current, child)):
        assert not cleanup()
        assert ledger.read().child == current_child
        assert ledger.read().state == "ACTIVE"


def test_child_replay_and_generation_regression_across_parents():
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    assert not ledger.attach(parent, child)
    assert ledger.revoke(parent, child)
    assert not ledger.attach(parent, child)
    assert not ledger.attach(parent, replace(child, run_id=uuid4()))
    assert ledger.stop(parent, "stop") and ledger.retire(parent)
    following = adopt(ledger, replace(identity, parent_id=uuid4()))
    assert not ledger.attach(following, child)
    assert ledger.attach(following, replace(child, run_id=uuid4(), generation=2))


def test_child_capacity_does_not_reset_when_parent_changes():
    ledger, identity, child, _ = fixture(max_children=1)
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    assert ledger.stop(parent, "stop") and ledger.retire(parent)
    following = adopt(ledger, replace(identity, parent_id=uuid4()))
    assert not ledger.attach(following, replace(child, run_id=uuid4(), generation=2))


@pytest.mark.parametrize("bad_clock", [9.9, math.nan, math.inf, True])
def test_clock_fault_is_not_cleared_by_new_parent(bad_clock):
    ledger, identity, _, clock = fixture()
    parent = adopt(ledger, identity)
    clock[0] = bad_clock
    assert ledger.read().state == "STOPPED"
    clock[0] = 10.0
    assert ledger.retire(parent)
    budget, _ = setup_budget()
    assert ledger.admit(replace(identity, parent_id=uuid4()), budget) is None


def test_expired_source_does_not_revive_on_child_change():
    ledger, identity, child, clock = fixture()
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    clock[0] = 10.5
    assert not ledger.revoke(parent, child)
    status = ledger.read()
    assert status.state == "STOPPED" and status.remaining is None
    assert not ledger.attach(parent, replace(child, run_id=uuid4(), generation=2))


@pytest.mark.parametrize("field,value", [("domain", "arm"), ("generation", True),
                                        ("generation", 0), ("boot_id", "boot")])
def test_malformed_child_rejected(field, value):
    _, _, child, _ = fixture()
    with pytest.raises(ValueError):
        replace(child, **{field: value})


def test_readback_does_not_grant_output_or_validate_physical_stop():
    ledger, identity, _, _ = fixture()
    parent = adopt(ledger, identity)
    assert ledger.read().state == "ACTIVE" and ledger.read().child is None
    assert ledger.stop(parent, "requested-stop")
    assert ledger.read().state == "STOPPED"
    # Retirement is metadata only. Native measured-stop/energy admission remains required.
    assert ledger.retire(parent)


def test_validation_delay_cannot_open_past_original_cutoff():
    ledger, identity, _, _ = fixture()
    values = iter([10.0, 10.11])
    ledger._clock = lambda: next(values)
    budget, _ = setup_budget()
    assert ledger.admit(identity, budget) is None
    assert budget.reason == "initial-admission-expired"
    ledger._clock = lambda: 10.11
    fresh, _ = setup_budget(before_mono=10.11, after_mono=10.11)
    assert ledger.admit(identity, fresh) is None


def test_source_expiring_during_child_validation_stays_closed():
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    values = iter([10.0, 10.5, 10.5])
    ledger._clock = lambda: next(values)
    assert not ledger.attach(parent, child)
    status = ledger.read()
    assert status.state == "STOPPED" and status.child is None


def test_value_copy_is_not_the_current_parent_handle():
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    copied = replace(parent)
    assert not ledger.attach(copied, child)
    assert not ledger.stop(copied, "copy")
    assert not ledger.retire(copied)
    assert ledger.read().state == "ACTIVE"


def test_different_parent_cannot_reset_an_active_window():
    ledger, identity, _, clock = fixture()
    adopt(ledger, identity)
    clock[0] = 10.2
    fresh, _ = setup_budget(before_mono=10.2, after_mono=10.2)
    assert ledger.admit(replace(identity, parent_id=uuid4()), fresh) is None
    assert ledger.read().parent == identity
    assert ledger.read().remaining.duration_s < 9.01


def test_child_boot_mismatch_does_not_attach():
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    assert not ledger.attach(parent, replace(child, boot_id=uuid4()))
    assert ledger.read().child is None


@pytest.mark.parametrize("field,value", [("parent_id", "id"), ("context_digest", "unverified"),
                                        ("map_revision", ""), ("odom_frame", " ")])
def test_malformed_parent_identity_rejected(field, value):
    _, identity, _, _ = fixture()
    with pytest.raises(ValueError):
        replace(identity, **{field: value})


def test_clock_exception_is_terminal_across_retirement():
    ledger, identity, _, _ = fixture()
    parent = adopt(ledger, identity)

    def broken_clock():
        raise OSError("synthetic clock failure")

    ledger._clock = broken_clock
    assert ledger.read().state == "STOPPED"
    assert ledger.retire(parent)
    ledger._clock = lambda: 10.0
    assert ledger.admit(replace(identity, parent_id=uuid4()), setup_budget()[0]) is None


def test_revoked_native_run_cannot_reattach_with_a_new_generation():
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child) and ledger.revoke(parent, child)
    assert not ledger.attach(parent, replace(child, generation=2))
    assert ledger.stop(parent, "stop") and ledger.retire(parent)
    following = adopt(ledger, replace(identity, parent_id=uuid4()))
    assert not ledger.attach(following, replace(child, generation=3))


def test_live_native_phase_advance_preserves_budget_and_consumed_run_capacity():
    ledger, identity, child, clock = fixture(max_children=1)
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    first = ledger.read()
    clock[0] = 10.2
    updated = replace(child, generation=2)
    assert ledger.advance(parent, child, updated)
    later = ledger.read()
    assert later.child == updated and later.epoch > first.epoch
    assert later.remaining.path_m < first.remaining.path_m - .199
    assert not ledger.advance(parent, child, replace(child, generation=3))
    assert ledger.revoke(parent, updated)
    assert not ledger.advance(parent, updated, replace(child, generation=3))
    assert not ledger.attach(parent, replace(child, run_id=uuid4(), generation=3))


@pytest.mark.parametrize("changes", [dict(domain="docking"), dict(boot_id=uuid4()),
                                     dict(run_id=uuid4()), dict(generation=1)])
def test_live_phase_advance_cannot_change_native_run_or_regress(changes):
    ledger, identity, child, _ = fixture()
    parent = adopt(ledger, identity)
    assert ledger.attach(parent, child)
    updated = dict(generation=2)
    updated.update(changes)
    attempted = replace(child, **updated)
    assert not ledger.advance(parent, child, attempted)
    assert ledger.read().child == child
